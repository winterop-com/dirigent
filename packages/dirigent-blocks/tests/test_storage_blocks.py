"""Tests for the generic storage blocks: everything addressed by URI, never by path."""

import json

import pytest
from pydantic import ValidationError

from dirigent_blocks.storage import (
    StorageCopyConfig,
    StorageCopyOperator,
    StorageCopyOutput,
    StorageExistsConfig,
    StorageExistsOutput,
    StorageExistsSensor,
    StorageReadOperator,
    StorageReadOutput,
    StorageWriteOperator,
    StorageWriteOutput,
)
from dirigent_blocks.transform_jq import JqTransformer
from dirigent_plugin import BlockFailure, ErrorClass, NotYet, TransformOutput
from dirigent_testing import FakeContext, FakeStorage, call_block


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


# -- storage.write ---------------------------------------------------------------


async def test_writing_text_puts_the_bytes_where_the_uri_says(ctx: FakeContext, storage: FakeStorage) -> None:
    output = await call_block(StorageWriteOperator(), {"target": "file://out/report.md", "text": "# Ærø\n"}, ctx)
    assert isinstance(output, StorageWriteOutput)
    assert (output.uri, output.bytes_written, output.content_type) == ("file://out/report.md", 8, "text/plain")
    assert storage.path_for("file://out/report.md").read_bytes() == "# Ærø\n".encode()


async def test_writing_a_value_writes_canonical_json(ctx: FakeContext, storage: FakeStorage) -> None:
    output = await call_block(
        StorageWriteOperator(), {"target": "file://out/rows.json", "value": {"b": 2, "a": [1, None]}}, ctx
    )
    assert isinstance(output, StorageWriteOutput)
    assert output.content_type == "application/json"
    assert storage.path_for("file://out/rows.json").read_bytes() == b'{"a":[1,null],"b":2}'


async def test_a_content_type_the_step_names_wins(ctx: FakeContext) -> None:
    output = await call_block(
        StorageWriteOperator(),
        {"target": "file://out/report.md", "text": "# title\n", "content_type": "text/markdown"},
        ctx,
    )
    assert isinstance(output, StorageWriteOutput)
    assert output.content_type == "text/markdown"


async def test_a_write_that_names_neither_text_nor_value_is_refused_at_validation(ctx: FakeContext) -> None:
    with pytest.raises(ValidationError, match="names neither"):
        await call_block(StorageWriteOperator(), {"target": "file://out/x"}, ctx)


async def test_a_write_that_names_both_is_refused_at_validation(ctx: FakeContext) -> None:
    with pytest.raises(ValidationError, match="names both"):
        await call_block(StorageWriteOperator(), {"target": "file://out/x", "text": "a", "value": 1}, ctx)


# -- storage.read ----------------------------------------------------------------


async def test_text_written_by_a_write_reads_back_as_text(ctx: FakeContext) -> None:
    await call_block(StorageWriteOperator(), {"target": "file://out/report.txt", "text": "two lines\nof it\n"}, ctx)

    output = await call_block(StorageReadOperator(), {"source": "file://out/report.txt"}, ctx)

    assert isinstance(output, StorageReadOutput)
    assert (output.text, output.value) == ("two lines\nof it\n", None)
    assert (output.content_type, output.bytes_read) == ("text/plain", 16)


async def test_a_value_written_by_a_write_reads_back_as_a_value(ctx: FakeContext) -> None:
    await call_block(StorageWriteOperator(), {"target": "file://out/rows.json", "value": [{"station": "st-1"}]}, ctx)

    output = await call_block(StorageReadOperator(), {"source": "file://out/rows.json"}, ctx)

    assert isinstance(output, StorageReadOutput)
    assert (output.value, output.text) == ([{"station": "st-1"}], None)
    assert output.content_type == "application/json"


async def test_the_extension_is_what_a_backend_that_records_nothing_is_read_by(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    put(storage, "file://drops/batch.json", b'{"count": 2}')

    output = await call_block(StorageReadOperator(), {"source": "file://drops/batch.json"}, ctx)

    assert isinstance(output, StorageReadOutput)
    assert output.value == {"count": 2}


async def test_the_override_decides_what_an_object_is_read_as(ctx: FakeContext, storage: FakeStorage) -> None:
    put(storage, "file://drops/batch.dat", b'{"count": 2}')

    output = await call_block(
        StorageReadOperator(), {"source": "file://drops/batch.dat", "content_type": "application/json"}, ctx
    )

    assert isinstance(output, StorageReadOutput)
    assert output.value == {"count": 2}


async def test_a_type_nothing_can_be_read_as_points_at_the_copy_block(ctx: FakeContext, storage: FakeStorage) -> None:
    put(storage, "file://drops/climate.parquet", b"PAR1")

    with pytest.raises(BlockFailure, match="storage.copy") as raised:
        await call_block(StorageReadOperator(), {"source": "file://drops/climate.parquet"}, ctx)

    assert raised.value.error_class is ErrorClass.REJECTED


async def test_an_object_larger_than_the_cap_is_rejected_rather_than_truncated(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    put(storage, "file://drops/big.json", b"[" + b"1," * 5000 + b"1]")

    with pytest.raises(BlockFailure, match="max_size") as raised:
        await call_block(StorageReadOperator(), {"source": "file://drops/big.json", "max_size": "1kb"}, ctx)

    assert raised.value.error_class is ErrorClass.REJECTED


async def test_reading_nothing_is_rejected_rather_than_retried(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure, match="nothing at") as raised:
        await call_block(StorageReadOperator(), {"source": "file://drops/absent.json"}, ctx)

    assert raised.value.error_class is ErrorClass.REJECTED


def test_the_write_and_read_operators_declare_themselves_idempotent() -> None:
    assert (StorageWriteOperator.spec.idempotent, StorageReadOperator.spec.idempotent) == (True, True)


# -- the composed path -----------------------------------------------------------


async def test_a_value_comes_in_through_a_read_and_goes_out_through_a_write(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    """The three hops a pipeline writes now: read the object, reshape the value, write it back."""
    put(storage, "file://drops/readings.json", b'[{"id": "r1", "c": 4}, {"id": "r2", "c": -3}]')

    read = await call_block(StorageReadOperator(), {"source": "file://drops/readings.json"}, ctx)
    assert isinstance(read, StorageReadOutput)

    reshaped = await call_block(
        JqTransformer(),
        {"input": read.value, "program": "[.[] | {id, fahrenheit: (.c * 9 / 5 + 32 | round)}]"},
        ctx,
    )
    assert isinstance(reshaped, TransformOutput)

    written = await call_block(
        StorageWriteOperator(),
        {"target": "file://out/fahrenheit.json", "value": reshaped.value},
        ctx,
    )
    assert isinstance(written, StorageWriteOutput)

    landed = storage.path_for("file://out/fahrenheit.json").read_bytes()
    assert json.loads(landed) == [{"fahrenheit": 39, "id": "r1"}, {"fahrenheit": 27, "id": "r2"}]
    assert written.content_type == "application/json"
    assert written.bytes_written == len(landed)
