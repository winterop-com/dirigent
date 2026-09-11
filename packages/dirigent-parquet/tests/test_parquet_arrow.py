"""Tests for ``convert.arrow``: parquet against the text formats, honestly typed."""

import datetime
import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from dirigent_parquet import ArrowConverter
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, FakeStorage, call_block

READINGS = [
    {"station": "st-1", "region": "east", "celsius": 4.5, "active": True},
    {"station": "st-2", "region": "west", "celsius": -3.0, "active": False},
]

READINGS_JSON = json.dumps(READINGS, separators=(",", ":"))


def column_types(payload: bytes) -> dict[str, pa.DataType]:
    """Read a written schema back, through the one seam the stub leaves untyped."""
    table = pq.read_table(pa.BufferReader(payload))  # pyright: ignore[reportUnknownMemberType]
    return dict(zip(table.schema.names, table.schema.types, strict=True))


def parquet_bytes(table: pa.Table) -> bytes:
    """Write one table as parquet bytes, through the same partially typed seam."""
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)  # pyright: ignore[reportUnknownMemberType]
    return sink.getvalue().to_pybytes()


async def to_parquet(ctx: FakeContext, storage: FakeStorage, text: str, source_format: str) -> bytes:
    """Convert one text payload to parquet bytes in storage, and hand them back."""
    storage.path_for("file://in.txt").write_text(text)
    output = await call_block(
        ArrowConverter(),
        {"source": "file://in.txt", "target": "file://out.parquet", "from": source_format, "to": "parquet"},
        ctx,
    )
    assert output.model_dump()["target"] == "file://out.parquet"
    return storage.path_for("file://out.parquet").read_bytes()


async def from_parquet(ctx: FakeContext, storage: FakeStorage, payload: bytes, target_format: str) -> str:
    """Convert parquet bytes in storage to one text payload."""
    storage.path_for("file://in.parquet").write_bytes(payload)
    await call_block(
        ArrowConverter(),
        {"source": "file://in.parquet", "target": "file://out.txt", "from": "parquet", "to": target_format},
        ctx,
    )
    return storage.path_for("file://out.txt").read_text()


def test_the_engine_is_convert_arrow_and_needs_no_allowlist_entry() -> None:
    assert ArrowConverter.spec.id == "convert.arrow"
    assert ArrowConverter.spec.group == "transform"
    assert ArrowConverter.spec.local_execution is False
    assert len(ArrowConverter.pairs) == 6


async def test_json_round_trips_through_parquet_with_its_types(ctx: FakeContext, storage: FakeStorage) -> None:
    payload = await to_parquet(ctx, storage, READINGS_JSON, "json")

    types = column_types(payload)
    assert types["station"] == pa.string()
    assert types["celsius"] == pa.float64()
    assert types["active"] == pa.bool_()
    assert json.loads(await from_parquet(ctx, storage, payload, "json")) == READINGS


async def test_ndjson_round_trips_through_parquet(ctx: FakeContext, storage: FakeStorage) -> None:
    lines = "".join(f"{json.dumps(row, separators=(',', ':'))}\n" for row in READINGS)

    payload = await to_parquet(ctx, storage, lines, "ndjson")

    assert await from_parquet(ctx, storage, payload, "ndjson") == lines


async def test_a_csv_writes_string_columns_because_csv_carries_no_types(ctx: FakeContext, storage: FakeStorage) -> None:
    source = "station,celsius\nst-1,4.5\nst-2,-3.0\n"

    payload = await to_parquet(ctx, storage, source, "csv")

    assert column_types(payload)["celsius"] == pa.string()
    assert await from_parquet(ctx, storage, payload, "csv") == source


async def test_a_csv_header_that_repeats_a_name_is_refused_naming_it_and_its_columns(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    """A record key names one column, so keeping the last value of two would drop a column silently."""
    with pytest.raises(BlockFailure) as raised:
        await to_parquet(ctx, storage, "a,b,a\n1,2,3\n", "csv")

    assert "the csv header repeats a column name: 'a' at columns 1, 3" in raised.value.message


async def test_a_csv_header_with_an_empty_name_is_refused_at_its_column(ctx: FakeContext, storage: FakeStorage) -> None:
    with pytest.raises(BlockFailure) as raised:
        await to_parquet(ctx, storage, "a,,b\n1,2,3\n", "csv")

    assert "the csv header has no name at column 2" in raised.value.message


async def test_parquet_to_csv_writes_typed_values_in_their_json_spelling(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    payload = await to_parquet(ctx, storage, READINGS_JSON, "json")

    produced = await from_parquet(ctx, storage, payload, "csv")

    assert produced == "station,region,celsius,active\nst-1,east,4.5,true\nst-2,west,-3.0,false\n"


async def test_integers_and_floats_unify_to_a_float_column(ctx: FakeContext, storage: FakeStorage) -> None:
    """JSON calls both a number, so 4 comes back as 4.0 rather than the column being refused."""
    source = json.dumps([{"count": 4}, {"count": 4.5}])

    payload = await to_parquet(ctx, storage, source, "json")

    assert json.loads(await from_parquet(ctx, storage, payload, "json")) == [{"count": 4.0}, {"count": 4.5}]


async def test_a_column_whose_rows_disagree_is_refused_naming_it(ctx: FakeContext, storage: FakeStorage) -> None:
    storage.path_for("file://in.txt").write_text(json.dumps([{"code": 7}, {"code": "st-1"}]))

    with pytest.raises(BlockFailure) as raised:
        await call_block(
            ArrowConverter(),
            {"source": "file://in.txt", "target": "file://out.parquet", "from": "json", "to": "parquet"},
            ctx,
        )

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "column 'code' holds both integer and string values" in raised.value.message


async def test_a_nested_value_is_refused_naming_the_row_and_the_key(ctx: FakeContext, storage: FakeStorage) -> None:
    storage.path_for("file://in.txt").write_text(json.dumps([{"station": "st-1", "tags": ["a"]}]))

    with pytest.raises(BlockFailure) as raised:
        await call_block(
            ArrowConverter(),
            {"source": "file://in.txt", "target": "file://out.parquet", "from": "json", "to": "parquet"},
            ctx,
        )

    assert "row 1 has a nested value at 'tags'" in raised.value.message


async def test_a_row_that_is_not_an_object_has_no_parquet_spelling(ctx: FakeContext, storage: FakeStorage) -> None:
    storage.path_for("file://in.txt").write_text(json.dumps([{"station": "st-1"}, 7]))

    with pytest.raises(BlockFailure) as raised:
        await call_block(
            ArrowConverter(),
            {"source": "file://in.txt", "target": "file://out.parquet", "from": "json", "to": "parquet"},
            ctx,
        )

    assert "element 2 of the input is not an object" in raised.value.message


async def test_a_missing_key_is_a_null_cell_and_an_all_null_column_is_strings(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    source = json.dumps([{"station": "st-1", "note": None}, {"station": "st-2"}])

    payload = await to_parquet(ctx, storage, source, "json")

    assert column_types(payload)["note"] == pa.string()
    assert json.loads(await from_parquet(ctx, storage, payload, "json")) == [
        {"station": "st-1", "note": None},
        {"station": "st-2", "note": None},
    ]


async def test_timestamps_come_back_as_iso_strings(ctx: FakeContext, storage: FakeStorage) -> None:
    table: pa.Table = pa.table(  # pyright: ignore[reportUnknownMemberType]
        {
            "station": ["st-1"],
            "seen_at": [datetime.datetime(2026, 9, 4, 12, 30, tzinfo=datetime.UTC)],
        }
    )

    produced = await from_parquet(ctx, storage, parquet_bytes(table), "json")

    assert json.loads(produced) == [{"station": "st-1", "seen_at": "2026-09-04T12:30:00+00:00"}]


async def test_a_nested_parquet_column_is_refused_naming_it(ctx: FakeContext, storage: FakeStorage) -> None:
    table: pa.Table = pa.table(  # pyright: ignore[reportUnknownMemberType]
        {"station": ["st-1"], "position": [{"lat": 9.0, "lon": 38.7}]}
    )
    storage.path_for("file://in.parquet").write_bytes(parquet_bytes(table))

    with pytest.raises(BlockFailure) as raised:
        await call_block(
            ArrowConverter(),
            {"source": "file://in.parquet", "target": "file://out.json", "from": "parquet", "to": "json"},
            ctx,
        )

    assert "column 'position'" in raised.value.message
    assert "flatten it before converting" in raised.value.message


async def test_a_binary_parquet_column_is_refused_naming_it(ctx: FakeContext, storage: FakeStorage) -> None:
    table: pa.Table = pa.table(  # pyright: ignore[reportUnknownMemberType]
        {"station": ["st-1"], "raw": [b"\x00\x01"]}
    )
    storage.path_for("file://in.parquet").write_bytes(parquet_bytes(table))

    with pytest.raises(BlockFailure) as raised:
        await call_block(
            ArrowConverter(),
            {"source": "file://in.parquet", "target": "file://out.json", "from": "parquet", "to": "json"},
            ctx,
        )

    assert "column 'raw' holds raw bytes" in raised.value.message


async def test_bytes_that_are_not_parquet_are_refused_as_such(ctx: FakeContext, storage: FakeStorage) -> None:
    storage.path_for("file://in.parquet").write_bytes(b"not parquet at all")

    with pytest.raises(BlockFailure) as raised:
        await call_block(
            ArrowConverter(),
            {"source": "file://in.parquet", "target": "file://out.json", "from": "parquet", "to": "json"},
            ctx,
        )

    assert "the input is not parquet" in raised.value.message


async def test_text_that_is_not_utf8_is_refused_at_the_byte_that_is_not(ctx: FakeContext, storage: FakeStorage) -> None:
    storage.path_for("file://in.txt").write_bytes(b"name\nGr\xe6nse\n")

    with pytest.raises(BlockFailure) as raised:
        await call_block(
            ArrowConverter(),
            {"source": "file://in.txt", "target": "file://out.parquet", "from": "csv", "to": "parquet"},
            ctx,
        )

    assert "at byte 7" in raised.value.message


async def test_a_json_value_that_is_not_an_array_is_refused(ctx: FakeContext, storage: FakeStorage) -> None:
    storage.path_for("file://in.txt").write_text(json.dumps({"station": "st-1"}))

    with pytest.raises(BlockFailure) as raised:
        await call_block(
            ArrowConverter(),
            {"source": "file://in.txt", "target": "file://out.parquet", "from": "json", "to": "parquet"},
            ctx,
        )

    assert "has to be a JSON array" in raised.value.message


def test_a_pair_this_engine_does_not_convert_is_refused_naming_the_six() -> None:
    from dirigent_plugin import ConvertConfig

    config = ConvertConfig.model_validate(
        {"source": "file://in.json", "target": "file://out.csv", "from": "json", "to": "csv"}
    )

    refusals = ArrowConverter().check_config(config)
    assert len(refusals) == 1
    assert "convert.arrow does not convert json to csv" in refusals[0]
    assert "parquet to json" in refusals[0]
