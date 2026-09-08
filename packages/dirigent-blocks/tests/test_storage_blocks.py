"""Tests for the generic storage blocks: everything addressed by URI, never by path."""

import pytest

from dirigent_blocks.storage import (
    StorageCopyConfig,
    StorageCopyOperator,
    StorageCopyOutput,
    StorageExistsConfig,
    StorageExistsOutput,
    StorageExistsSensor,
)
from dirigent_plugin import BlockFailure, ErrorClass, NotYet
from dirigent_testing import FakeContext, FakeStorage


def put(storage: FakeStorage, uri: str, payload: bytes) -> None:
    """Place an object at a URI without going through a block."""
    path = storage.path_for(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


# -- storage.copy ----------------------------------------------------------------


async def test_a_copy_streams_the_object_and_reports_what_it_moved(ctx: FakeContext, storage: FakeStorage) -> None:
    put(storage, "file://in/data.csv", b"a,b,c\n1,2,3\n")
    config = StorageCopyConfig(source="file://in/data.csv", target="file://out/data.csv")
    output = await StorageCopyOperator().execute(config, ctx.as_context())
    assert isinstance(output, StorageCopyOutput)
    assert output.bytes_copied == 12
    assert storage.path_for("file://out/data.csv").read_bytes() == b"a,b,c\n1,2,3\n"
    assert "copied" in ctx.log.messages()


async def test_copying_a_large_object_does_not_depend_on_one_chunk(ctx: FakeContext, storage: FakeStorage) -> None:
    payload = b"x" * 100_000
    put(storage, "file://in/big.bin", payload)
    output = await StorageCopyOperator().execute(
        StorageCopyConfig(source="file://in/big.bin", target="file://out/big.bin"), ctx.as_context()
    )
    assert isinstance(output, StorageCopyOutput)
    assert output.bytes_copied == len(payload)
    assert storage.path_for("file://out/big.bin").read_bytes() == payload


async def test_copying_from_nothing_is_rejected_rather_than_retried(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await StorageCopyOperator().execute(
            StorageCopyConfig(source="file://in/absent.csv", target="file://out/x"), ctx.as_context()
        )
    assert raised.value.error_class is ErrorClass.REJECTED


def test_the_copy_operator_declares_itself_idempotent() -> None:
    assert StorageCopyOperator.spec.idempotent is True


# -- storage.exists --------------------------------------------------------------


async def test_the_sensor_waits_until_the_object_appears(ctx: FakeContext, storage: FakeStorage) -> None:
    config = StorageExistsConfig(uri="file://drops/climate.parquet")
    assert isinstance(await StorageExistsSensor().poke(config, ctx.as_context()), NotYet)

    put(storage, "file://drops/climate.parquet", b"parquet")
    observed = await StorageExistsSensor().poke(config, ctx.as_context())
    assert isinstance(observed, StorageExistsOutput)
    assert observed.uri == "file://drops/climate.parquet"
    assert observed.size == 7
    assert observed.modified_at.tzinfo is not None


async def test_the_sensor_matches_a_glob(ctx: FakeContext, storage: FakeStorage) -> None:
    config = StorageExistsConfig(uri="file://drops/*.parquet")
    assert isinstance(await StorageExistsSensor().poke(config, ctx.as_context()), NotYet)

    put(storage, "file://drops/ignored.txt", b"no")
    assert isinstance(await StorageExistsSensor().poke(config, ctx.as_context()), NotYet)

    put(storage, "file://drops/wanted.parquet", b"yes")
    observed = await StorageExistsSensor().poke(config, ctx.as_context())
    assert isinstance(observed, StorageExistsOutput)
    assert observed.uri.endswith("wanted.parquet")


async def test_the_sensor_ignores_an_object_that_is_still_too_small(ctx: FakeContext, storage: FakeStorage) -> None:
    config = StorageExistsConfig(uri="file://drops/partial.bin", min_size=10)
    put(storage, "file://drops/partial.bin", b"short")
    assert isinstance(await StorageExistsSensor().poke(config, ctx.as_context()), NotYet)

    put(storage, "file://drops/partial.bin", b"long enough now")
    assert isinstance(await StorageExistsSensor().poke(config, ctx.as_context()), StorageExistsOutput)


async def test_the_sensor_ignores_a_glob_match_that_is_too_small(ctx: FakeContext, storage: FakeStorage) -> None:
    config = StorageExistsConfig(uri="file://drops/*.bin", min_size=10)
    put(storage, "file://drops/small.bin", b"tiny")
    assert isinstance(await StorageExistsSensor().poke(config, ctx.as_context()), NotYet)
