"""URI-addressed storage: a facade that dispatches by scheme, and the ``file://`` backend.

Nothing ever passes a worker-local filesystem path between steps, so a step landing on a
different worker than its predecessor still sees its inputs.
"""

import asyncio
import os
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Iterable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, ClassVar, Final
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel

from dirigent_plugin import ByteSink, StatResult, StorageBackend

CHUNK_SIZE: Final = 256 * 1024

GLOB_CHARACTERS: Final = ("*", "?", "[")


class StorageError(Exception):
    """Any failure raised by the storage layer itself, as opposed to by a block."""


class UnknownScheme(StorageError):
    """A URI named a scheme no registered backend claims."""

    def __init__(self, scheme: str, known: Iterable[str]) -> None:
        """Name the scheme and the schemes that are registered."""
        registered = ", ".join(sorted(known)) or "none"
        super().__init__(f"no storage backend registered for scheme {scheme!r}; registered schemes: {registered}")
        self.scheme = scheme


class OutsideRoot(StorageError):
    """A ``file://`` URI resolved outside the configured artifact root."""

    def __init__(self, uri: str, root: Path) -> None:
        """Name the URI and the boundary it crossed."""
        super().__init__(f"{uri!r} resolves outside the artifact root {str(root)!r}")
        self.uri = uri


def parse_uri(uri: str) -> tuple[str, str]:
    """Split a URI into its scheme and the backend-specific remainder."""
    split = urlsplit(uri)
    if not split.scheme:
        raise StorageError(f"{uri!r} is not a URI: it names no scheme")
    return split.scheme, f"{split.netloc}{split.path}"


def join_uri(prefix: str, *parts: str) -> str:
    """Join a URI prefix with path segments, collapsing the separators."""
    trimmed = [part.strip("/") for part in parts if part.strip("/")]
    return "/".join([prefix.rstrip("/"), *trimmed])


def scratch_prefix(artifact_root: str, run_id: UUID) -> str:
    """Return the run-scoped URI prefix blocks write intermediates under."""
    return join_uri(artifact_root, "runs", str(run_id))


def work_dir(work_root: str, run_id: UUID) -> Path:
    """Return the run's directory on this worker's own filesystem, as an absolute path.

    The counterpart of :func:`scratch_prefix` for what a tool must open through the
    filesystem. It is not created here: reading the path is not the same as needing it.
    """
    return (Path(work_root).expanduser() / "runs" / str(run_id)).absolute()


def local_path(location: str) -> Path:
    """Turn a ``file://`` URI, or the path part of one, into a normalised absolute path."""
    if location.startswith("file://"):
        _, location = parse_uri(location)
    expanded = Path(location).expanduser()
    return Path(os.path.normpath(expanded if expanded.is_absolute() else Path.cwd() / expanded))


class FileStorageConfig(BaseModel):
    """Configuration for the local ``file://`` backend."""

    root: str = "./artifacts"


class FileSink:
    """The write end of a local file, staged beside its target and renamed on close."""

    def __init__(self, handle: BinaryIO, path: Path) -> None:
        """Hold the open file and the path it will be published onto."""
        self._handle = handle
        self.path = path
        self.written = 0

    async def write(self, data: bytes) -> int:
        """Append bytes to the staged file."""
        written = await asyncio.to_thread(self._handle.write, data)
        self.written += written
        return written


class FileStorageBackend(StorageBackend):
    """Streams bytes to and from a directory tree, refusing anything outside its root."""

    scheme: ClassVar[str] = "file"
    config_model: ClassVar[type[BaseModel]] = FileStorageConfig

    def __init__(self, root: str | Path) -> None:
        """Bind the backend to the directory every ``file://`` URI must resolve inside."""
        self.root = local_path(str(root))

    def path_for(self, uri: str) -> Path:
        """Resolve a URI to a contained local path, or refuse it.

        Containment is checked on the *resolved* path, not the lexical one. Normalising
        ``..`` away is not enough when a symlink can point anywhere: ``shell.run`` works
        inside the run's scratch directory, so a step that runs ``ln -s /etc scratch/etc``
        and then asks storage for ``file://.../scratch/etc/shadow`` clears a lexical check
        with room to spare and ``open_read`` follows the link. Resolving first turns the
        containment check into a statement about the file that is actually opened.
        """
        scheme, remainder = parse_uri(uri)
        if scheme != self.scheme:
            raise UnknownScheme(scheme, [self.scheme])
        path = local_path(remainder)
        # strict=False, because the path of a file about to be written does not exist yet;
        # what matters is that every component that *does* exist resolves inside the root.
        resolved = path.resolve()
        root = self.root.resolve()
        if resolved != root and not resolved.is_relative_to(root):
            raise OutsideRoot(uri, self.root)
        return path

    def uri_for(self, path: Path) -> str:
        """Render a contained local path back as the URI a caller would use."""
        return f"file://{path}"

    async def open_read(self, uri: str) -> AsyncGenerator[bytes]:
        """Stream the object at a URI in bounded chunks."""
        path = self.path_for(uri)
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(handle.read, CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    @asynccontextmanager
    async def _writer(self, uri: str) -> AsyncGenerator[ByteSink]:
        """Open a staged writer, publishing it onto the target only on a clean exit."""
        path = self.path_for(uri)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        # The nonce is per writer: two writers on one URI must not share a staging file.
        staged = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.partial")
        handle = await asyncio.to_thread(staged.open, "wb")
        sink = FileSink(handle, path)
        try:
            yield sink
        except BaseException:
            await asyncio.to_thread(handle.close)
            await asyncio.to_thread(staged.unlink, True)
            raise
        await asyncio.to_thread(handle.close)
        # Staging beside the target keeps both on one filesystem, where os.replace is atomic.
        await asyncio.to_thread(os.replace, staged, path)

    def open_write(self, uri: str) -> AbstractAsyncContextManager[ByteSink]:
        """Open a streamed writer for a URI; the object appears only once writing finished."""
        return self._writer(uri)

    async def stat(self, uri: str) -> StatResult | None:
        """Describe the object at a URI, or return None when it does not exist."""
        path = self.path_for(uri)
        info = await asyncio.to_thread(_stat_file, path)
        if info is None:
            return None
        return StatResult(uri=self.uri_for(path), size=info[0], modified_at=info[1])

    def matches(self, uri: str) -> list[Path]:
        """Expand a listing URI into the sorted set of files it names."""
        scheme, remainder = parse_uri(uri)
        if scheme != self.scheme:
            raise UnknownScheme(scheme, [self.scheme])
        if not any(character in remainder for character in GLOB_CHARACTERS):
            path = self.path_for(uri)
            if path.is_file():
                return [path]
            if not path.is_dir():
                return []
            return sorted(child for child in path.rglob("*") if child.is_file())
        pattern = str(local_path(remainder))
        base = self.path_for(f"file://{_fixed_prefix(pattern)}")
        return sorted(path for path in base.rglob("*") if path.is_file() and path.full_match(pattern))

    async def list(self, uri: str) -> AsyncIterator[StatResult]:
        """List the files under a prefix, or the files matching a glob pattern."""
        for path in await asyncio.to_thread(self.matches, uri):
            info = await asyncio.to_thread(_stat_file, path)
            if info is not None:
                yield StatResult(uri=self.uri_for(path), size=info[0], modified_at=info[1])

    async def delete(self, uri: str) -> None:
        """Remove the object at a URI; deleting what is not there is not an error."""
        path = self.path_for(uri)
        await asyncio.to_thread(path.unlink, True)


def _fixed_prefix(pattern: str) -> str:
    """Return the deepest directory of a glob pattern that contains no wildcard."""
    parts: list[str] = []
    for part in Path(pattern).parts:
        if any(character in part for character in GLOB_CHARACTERS):
            break
        parts.append(part)
    return str(Path(*parts)) if parts else "/"


def _stat_file(path: Path) -> tuple[int, datetime] | None:
    """Return a file's size and modification time, or None when it is not a file."""
    try:
        info = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return info.st_size, datetime.fromtimestamp(info.st_mtime, tz=UTC)


class Storage:
    """The engine's storage facade: one URI namespace over every registered backend."""

    def __init__(
        self,
        backends: Mapping[str, StorageBackend],
        artifact_root: str,
        binder: "Callable[[str, StorageBackend], StorageBackend] | None" = None,
    ) -> None:
        """Bind the facade to the scheme index, the default scratch root, and how a scheme is configured."""
        self._backends = dict(backends)
        self.artifact_root = artifact_root.rstrip("/")
        self._binder = binder
        #: Schemes already configured through the binder; mutable, and therefore private to
        #: one attempt: see :class:`AttemptStorage`.
        self._bound: dict[str, StorageBackend] = {}

    @property
    def schemes(self) -> list[str]:
        """List the schemes this instance can address."""
        return sorted(self._backends)

    def backend_for(self, uri: str) -> StorageBackend:
        """Resolve the backend a URI belongs to, or say which schemes exist."""
        scheme, _ = parse_uri(uri)
        backend = self._bound.get(scheme) or self._backends.get(scheme)
        if backend is None:
            raise UnknownScheme(scheme, self._backends)
        if self._binder is not None and scheme not in self._bound:
            backend = self._binder(scheme, backend)
            self._bound[scheme] = backend
        return backend

    def bound_by(self, binder: "Callable[[str, StorageBackend], StorageBackend]") -> "AttemptStorage":
        """Return the same namespace as an attempt-scoped facade, configured on first use.

        A new facade rather than a mutation: the process-wide one is shared by every attempt,
        and one attempt must not reconfigure a scheme under another.
        """
        return AttemptStorage(self._backends, self.artifact_root, binder)

    def scratch_for(self, run_id: UUID) -> str:
        """Return the run-scoped prefix a block writes intermediates under."""
        return scratch_prefix(self.artifact_root, run_id)

    def open_read(self, uri: str) -> AsyncGenerator[bytes]:
        """Stream the object at a URI."""
        return self.backend_for(uri).open_read(uri)

    def open_write(self, uri: str) -> AbstractAsyncContextManager[ByteSink]:
        """Open a streamed writer for a URI."""
        return self.backend_for(uri).open_write(uri)

    async def stat(self, uri: str) -> StatResult | None:
        """Describe the object at a URI, or return None when it does not exist."""
        return await self.backend_for(uri).stat(uri)

    def list(self, uri: str) -> AsyncIterator[StatResult]:
        """List the objects under a URI prefix or matching a glob."""
        return self.backend_for(uri).list(uri)

    async def delete(self, uri: str) -> None:
        """Remove the object at a URI."""
        await self.backend_for(uri).delete(uri)

    async def delete_prefix(self, uri: str) -> int:
        """Remove every object under a prefix, and say how many went.

        Built out of ``list`` and ``delete`` rather than asked of the backend, so a backend
        written before this existed still prunes. A backend with a bulk delete of its own is
        free to answer faster; the contract is what is gone, not how many requests it took.
        """
        deleted = 0
        for entry in [found async for found in self.list(uri)]:
            await self.delete(entry.uri)
            deleted += 1
        return deleted

    async def read_bytes(self, uri: str) -> bytes:
        """Read a whole object into memory; only for values the engine knows are small."""
        chunks = [chunk async for chunk in self.open_read(uri)]
        return b"".join(chunks)

    async def write_bytes(self, uri: str, data: bytes) -> int:
        """Write a whole object in one call, streaming it through the backend."""
        async with self.open_write(uri) as sink:
            return await sink.write(data)

    async def copy(self, source: str, target: str) -> int:
        """Stream one object onto another, across backends, without buffering it whole."""
        copied = 0
        async with self.open_write(target) as sink:
            async for chunk in self.open_read(source):
                copied += await sink.write(chunk)
        return copied


class AttemptStorage(Storage):
    """A storage facade belonging to exactly one attempt.

    The binder opens connection secrets and the backend it returns is cached for the life of
    the facade, so sharing one across attempts would hand one attempt's credentials to
    another.
    """


def build_storage(artifact_root: str, backends: Iterable[StorageBackend] = ()) -> Storage:
    """Assemble the facade: the plugin-contributed backends plus ``file://`` from core."""
    scheme, remainder = parse_uri(artifact_root)
    index: dict[str, StorageBackend] = {backend.scheme: backend for backend in backends}
    if scheme == FileStorageBackend.scheme and scheme not in index:
        index[scheme] = FileStorageBackend(remainder)
    return Storage(index, artifact_root)
