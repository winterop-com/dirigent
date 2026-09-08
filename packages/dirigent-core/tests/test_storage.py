"""Tests for the storage facade and the file:// backend's contract."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from dirigent_core.ids import uuid7
from dirigent_core.storage import (
    FileStorageBackend,
    OutsideRoot,
    Storage,
    StorageError,
    UnknownScheme,
    build_storage,
    join_uri,
    parse_uri,
    scratch_prefix,
    work_dir,
)
from dirigent_plugin import ByteSink, StatResult, StorageBackend


@pytest.fixture
def backend(tmp_path: Path) -> FileStorageBackend:
    """A file backend rooted at a throwaway directory."""
    return FileStorageBackend(tmp_path)


@pytest.fixture
def storage(tmp_path: Path) -> Storage:
    """A facade whose only scheme is the file backend under a throwaway root."""
    return build_storage(f"file://{tmp_path}")


def test_parse_uri_splits_scheme_from_location() -> None:
    assert parse_uri("file://./artifacts/x.json") == ("file", "./artifacts/x.json")
    assert parse_uri("file:///var/data/x") == ("file", "/var/data/x")
    assert parse_uri("s3://bucket/key") == ("s3", "bucket/key")


def test_parse_uri_refuses_a_bare_path() -> None:
    with pytest.raises(StorageError, match="names no scheme"):
        parse_uri("/var/data/x")


def test_join_uri_collapses_separators() -> None:
    assert join_uri("file://root/", "/a/", "b") == "file://root/a/b"
    assert join_uri("file://root", "", "b") == "file://root/b"


def test_scratch_prefix_namespaces_a_run() -> None:
    run_id = uuid7()
    assert scratch_prefix("file://./artifacts", run_id) == f"file://./artifacts/runs/{run_id}"


def test_a_work_directory_is_run_scoped_and_absolute() -> None:
    """A child process is given a working directory and the paths it touches, so both are absolute."""
    run_id = uuid7()
    directory = work_dir("./.dirigent/state/work", run_id)
    assert directory.is_absolute()
    assert directory == Path.cwd() / ".dirigent/state/work/runs" / str(run_id)
    assert not directory.exists(), "reading the path is not the same as needing it"


async def test_write_then_read_round_trips(storage: Storage, tmp_path: Path) -> None:
    uri = f"file://{tmp_path}/nested/deep/value.txt"
    assert await storage.write_bytes(uri, b"hello") == 5
    assert await storage.read_bytes(uri) == b"hello"


async def test_a_write_is_only_visible_once_it_finished(backend: FileStorageBackend, tmp_path: Path) -> None:
    uri = f"file://{tmp_path}/partial.txt"
    with pytest.raises(RuntimeError, match="boom"):
        async with backend.open_write(uri) as sink:
            await sink.write(b"half")
            raise RuntimeError("boom")
    assert await backend.stat(uri) is None
    assert list(tmp_path.iterdir()) == []


async def test_two_concurrent_writers_to_one_uri_do_not_share_a_staging_file(
    backend: FileStorageBackend, tmp_path: Path
) -> None:
    """One published payload, whole: never a weave of both."""
    uri = f"file://{tmp_path}/latest.csv"
    turns = [asyncio.Event(), asyncio.Event()]
    turns[0].set()

    async def write(index: int, letter: bytes) -> None:
        async with backend.open_write(uri) as sink:
            for _ in range(4):
                await turns[index].wait()
                turns[index].clear()
                await sink.write(letter * 16)
                turns[1 - index].set()

    await asyncio.gather(write(0, b"a"), write(1, b"b"))

    assert (tmp_path / "latest.csv").read_bytes() in (b"a" * 64, b"b" * 64)
    assert list(tmp_path.iterdir()) == [tmp_path / "latest.csv"]


async def test_a_failing_writer_does_not_disturb_a_concurrent_one(backend: FileStorageBackend, tmp_path: Path) -> None:
    """A writer that raises takes only its own staging file with it."""
    uri = f"file://{tmp_path}/latest.csv"
    started = asyncio.Event()
    wrote = asyncio.Event()
    cleaned = asyncio.Event()

    async def doomed() -> None:
        try:
            async with backend.open_write(uri) as sink:
                await sink.write(b"a" * 16)
                started.set()
                await wrote.wait()
                raise RuntimeError("boom")
        finally:
            cleaned.set()

    async def survivor() -> None:
        async with backend.open_write(uri) as sink:
            await started.wait()
            await sink.write(b"b" * 16)
            wrote.set()
            await cleaned.wait()
            await sink.write(b"b" * 16)

    failure, survived = await asyncio.gather(doomed(), survivor(), return_exceptions=True)

    assert isinstance(failure, RuntimeError)
    assert survived is None
    assert (tmp_path / "latest.csv").read_bytes() == b"b" * 32
    assert list(tmp_path.iterdir()) == [tmp_path / "latest.csv"]


async def test_reading_streams_in_chunks(backend: FileStorageBackend, tmp_path: Path) -> None:
    payload = b"x" * (600 * 1024)
    uri = f"file://{tmp_path}/big.bin"
    async with backend.open_write(uri) as sink:
        await sink.write(payload)
    chunks = [chunk async for chunk in backend.open_read(uri)]
    assert len(chunks) == 3
    assert b"".join(chunks) == payload


async def test_stat_describes_an_object_and_returns_none_for_a_gap(backend: FileStorageBackend, tmp_path: Path) -> None:
    uri = f"file://{tmp_path}/present.json"
    await FileSinkHelper.write(backend, uri, b'{"a": 1}')
    result = await backend.stat(uri)
    assert result is not None
    assert result.size == 8
    assert result.uri == uri
    assert result.modified_at.tzinfo is not None
    assert await backend.stat(f"file://{tmp_path}/absent.json") is None
    assert await backend.stat(f"file://{tmp_path}") is None


async def test_list_walks_a_prefix(backend: FileStorageBackend, tmp_path: Path) -> None:
    for name in ("a.txt", "sub/b.txt", "sub/c.json"):
        await FileSinkHelper.write(backend, f"file://{tmp_path}/{name}", b"x")
    found = [result.uri async for result in backend.list(f"file://{tmp_path}")]
    assert found == [
        f"file://{tmp_path}/a.txt",
        f"file://{tmp_path}/sub/b.txt",
        f"file://{tmp_path}/sub/c.json",
    ]


async def test_list_matches_a_glob(backend: FileStorageBackend, tmp_path: Path) -> None:
    for name in ("a.txt", "sub/b.txt", "sub/c.json"):
        await FileSinkHelper.write(backend, f"file://{tmp_path}/{name}", b"x")
    recursive = [result.uri async for result in backend.list(f"file://{tmp_path}/**/*.txt")]
    assert recursive == [f"file://{tmp_path}/a.txt", f"file://{tmp_path}/sub/b.txt"]
    shallow = [result.uri async for result in backend.list(f"file://{tmp_path}/*.txt")]
    assert shallow == [f"file://{tmp_path}/a.txt"]
    deep = [result.uri async for result in backend.list(f"file://{tmp_path}/sub/*.json")]
    assert deep == [f"file://{tmp_path}/sub/c.json"]


async def test_list_of_a_missing_prefix_is_empty(backend: FileStorageBackend, tmp_path: Path) -> None:
    assert [result async for result in backend.list(f"file://{tmp_path}/nothing-here")] == []


async def test_delete_is_idempotent(backend: FileStorageBackend, tmp_path: Path) -> None:
    uri = f"file://{tmp_path}/gone.txt"
    await FileSinkHelper.write(backend, uri, b"x")
    await backend.delete(uri)
    await backend.delete(uri)
    assert await backend.stat(uri) is None


async def test_the_backend_refuses_to_escape_its_root(backend: FileStorageBackend, tmp_path: Path) -> None:
    with pytest.raises(OutsideRoot):
        backend.path_for("file:///etc/passwd")
    with pytest.raises(OutsideRoot):
        backend.path_for(f"file://{tmp_path}/../outside.txt")


def test_the_backend_refuses_another_scheme(backend: FileStorageBackend) -> None:
    with pytest.raises(UnknownScheme):
        backend.path_for("s3://bucket/key")


def test_the_facade_names_the_schemes_it_has(storage: Storage) -> None:
    assert storage.schemes == ["file"]
    with pytest.raises(UnknownScheme, match="registered schemes: file"):
        storage.backend_for("s3://bucket/key")


def test_the_facade_scratch_prefix_is_run_scoped(storage: Storage, tmp_path: Path) -> None:
    run_id = uuid7()
    assert storage.scratch_for(run_id) == f"file://{tmp_path}/runs/{run_id}"


async def test_copy_streams_between_uris(storage: Storage, tmp_path: Path) -> None:
    source = f"file://{tmp_path}/in/data.bin"
    target = f"file://{tmp_path}/out/data.bin"
    await storage.write_bytes(source, b"y" * 300_000)
    assert await storage.copy(source, target) == 300_000
    assert await storage.read_bytes(target) == b"y" * 300_000


async def test_facade_stat_list_and_delete_dispatch(storage: Storage, tmp_path: Path) -> None:
    uri = f"file://{tmp_path}/dispatch.txt"
    await storage.write_bytes(uri, b"abc")
    assert (await storage.stat(uri)) is not None
    assert [result.uri async for result in storage.list(f"file://{tmp_path}")] == [uri]
    await storage.delete(uri)
    assert await storage.stat(uri) is None


def test_build_storage_prefers_a_contributed_backend(tmp_path: Path) -> None:
    class MemoryConfig(BaseModel):
        pass

    class MemoryBackend(StorageBackend):
        scheme = "memory"
        config_model = MemoryConfig

        def open_read(self, uri: str) -> AsyncGenerator[bytes]:
            raise NotImplementedError

        def open_write(self, uri: str) -> AbstractAsyncContextManager[ByteSink]:
            raise NotImplementedError

        async def stat(self, uri: str) -> StatResult | None:
            return None

        def list(self, uri: str) -> AsyncIterator[StatResult]:
            raise NotImplementedError

        async def delete(self, uri: str) -> None:
            return None

    assembled = build_storage(f"file://{tmp_path}", [MemoryBackend()])
    assert assembled.schemes == ["file", "memory"]


class FileSinkHelper:
    """Writes a whole payload through the streamed interface."""

    @staticmethod
    async def write(backend: FileStorageBackend, uri: str, payload: bytes) -> None:
        """Stream a payload into a URI through the backend's writer."""
        async with backend.open_write(uri) as sink:
            await sink.write(payload)


async def test_a_symlink_inside_the_artifact_root_cannot_escape_it(tmp_path: Path) -> None:
    """Lexical containment is not containment when something inside the root can point out."""
    root = tmp_path / "artifacts"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("not yours")
    (root / "runs").mkdir(parents=True)
    (root / "runs" / "escape").symlink_to(outside, target_is_directory=True)

    backend = FileStorageBackend(root)

    with pytest.raises(OutsideRoot):
        backend.path_for(f"file://{root}/runs/escape/secret.txt")
    with pytest.raises(OutsideRoot):
        async with backend.open_write(f"file://{root}/runs/escape/planted.txt") as sink:
            await sink.write(b"nope")
    assert not (outside / "planted.txt").exists()


async def test_a_path_that_does_not_exist_yet_is_still_contained(tmp_path: Path) -> None:
    """Writes address files that do not exist, so resolution must tolerate a missing tail."""
    root = tmp_path / "artifacts"
    backend = FileStorageBackend(root)
    async with backend.open_write(f"file://{root}/runs/abc/new/deep.txt") as sink:
        await sink.write(b"fine")
    assert (root / "runs" / "abc" / "new" / "deep.txt").read_bytes() == b"fine"


def test_two_attempts_never_share_a_bound_backend() -> None:
    """A bound backend carries one attempt's credentials, so a second attempt must not get it.

    The facade caches what its binder returned, which is what makes that safe -- and is only
    safe while each attempt asks for its own facade. This is that, as a constraint rather than
    a property of a type nothing checks.
    """
    opened: list[str] = []

    def binder_for(name: str) -> Callable[[str, StorageBackend], StorageBackend]:
        def bind(scheme: str, backend: StorageBackend) -> StorageBackend:
            opened.append(name)
            return backend

        return bind

    storage = build_storage("file:///tmp/artifacts")

    first = storage.bound_by(binder_for("first"))
    second = storage.bound_by(binder_for("second"))

    assert first is not second, "two attempts were handed one facade"
    first.backend_for("file:///tmp/artifacts/a")
    first.backend_for("file:///tmp/artifacts/b")
    second.backend_for("file:///tmp/artifacts/c")
    assert opened == ["first", "second"], "a facade bound a scheme more than once, or shared what another bound"


def test_binding_does_not_reconfigure_the_shared_facade() -> None:
    """The process-wide facade is every attempt's, so binding one must leave it untouched."""
    storage = build_storage("file:///tmp/artifacts")
    plain = storage.backend_for("file:///tmp/artifacts/a")

    storage.bound_by(lambda scheme, backend: _Refusing()).backend_for("file:///tmp/artifacts/a")

    assert storage.backend_for("file:///tmp/artifacts/a") is plain


class _Refusing(StorageBackend):
    """A backend that would be wrong to hand to anybody else."""

    scheme = "file"

    def open_read(self, uri: str) -> Any:  # pragma: no cover - never called
        raise AssertionError

    def open_write(self, uri: str) -> Any:  # pragma: no cover - never called
        raise AssertionError

    async def stat(self, uri: str) -> Any:  # pragma: no cover - never called
        raise AssertionError

    def list(self, uri: str) -> Any:  # pragma: no cover - never called
        raise AssertionError

    async def delete(self, uri: str) -> None:  # pragma: no cover - never called
        raise AssertionError
