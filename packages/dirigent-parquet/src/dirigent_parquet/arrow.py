"""The ``arrow`` engine for the convert verb: parquet against the text formats, on pyarrow."""

import csv
import io
import json
from typing import Final

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, JsonValue

from dirigent_common import spelled
from dirigent_plugin import (
    BlockFailure,
    ConvertConfig,
    Converter,
    ConvertOutput,
    ErrorClass,
    RemoteHandle,
    StepContext,
    TransformError,
)

#: The text spellings this engine trades parquet with.
TEXT_FORMATS: Final = ("json", "ndjson", "csv")

#: What a target format calls one element of the sequence it writes.
UNIT: Final = {"json": "element", "ndjson": "line", "csv": "row", "parquet": "row"}

#: Why parquet only ever travels by URI, said once and reused by both refusals.
BYTES_BY_URI: Final = "parquet is bytes, and bytes travel by uri"


class ArrowConverter(Converter):
    """Re-encodes a sequence of records between parquet and the text formats.

    The record model is ``convert.std``'s: a sequence of flat records, read out of one
    spelling and written in another. What parquet adds is types -- a column knows whether it
    holds numbers or text -- so writing infers a schema from the records, and a column whose
    rows disagree about their type is refused naming it rather than coerced. Reading gives
    every value its JSON spelling: timestamps, dates and times come back as ISO strings,
    decimals as strings, and a float that is NaN or infinite as null, because JSON has no
    other words for them.

    A csv carries no types, so csv to parquet writes string columns and nothing else.

    Parquet is bytes rather than text, so it always travels by uri: the parquet side of a
    conversion is ``input_uri`` in and ``save_to`` out, never the inline ``input`` field.
    """

    kind = "arrow"
    summary = "Convert between parquet and the text formats."
    pairs = frozenset({("parquet", text) for text in TEXT_FORMATS} | {(text, "parquet") for text in TEXT_FORMATS})

    def check_config(self, config: BaseModel) -> list[str]:
        """Refuse the pair, and a parquet side asked to travel inline, at apply."""
        issues = super().check_config(config)
        if isinstance(config, ConvertConfig):
            issues.extend(_inline_refusals(config))
        return issues

    async def execute(self, config: ConvertConfig, ctx: StepContext) -> ConvertOutput | RemoteHandle:
        """Guard the uri rule again at run time, then let the frame do its work.

        A config whose formats arrived through references is checked here for the first
        time, because apply deferred it.
        """
        refused = _inline_refusals(config)
        if refused:
            raise BlockFailure(refused[0], error_class=ErrorClass.REJECTED)
        return await super().execute(config, ctx)

    def convert(self, source: bytes, *, source_format: str, target_format: str) -> bytes:
        """Read the records out of the source format and write them in the target format."""
        if source_format == "parquet":
            records = _read_parquet(source, target_format)
        else:
            records = _read_text(source, source_format, target_format)
        if target_format == "parquet":
            return _write_parquet(records)
        return _write_text(records, target_format).encode()


def _inline_refusals(config: ConvertConfig) -> list[str]:
    """Word the refusals of a parquet payload written or asked for inline."""
    issues: list[str] = []
    if config.from_format == "parquet" and config.input is not None:
        issues.append(f"a parquet input is read from input_uri, not written inline: {BYTES_BY_URI}")
    if config.to_format == "parquet" and config.save_to is None:
        issues.append(f"a parquet result needs save_to, because it cannot inline: {BYTES_BY_URI}")
    return issues


def _read_parquet(source: bytes, target_format: str) -> list[dict[str, JsonValue]]:
    """Read a parquet payload as records, refusing what the target has no spelling for."""
    try:
        table = pq.read_table(pa.BufferReader(source))  # pyright: ignore[reportUnknownMemberType]
    except pa.ArrowInvalid as error:
        raise TransformError(f"the input is not parquet: {error}") from error
    for name, kind in zip(table.schema.names, table.schema.types, strict=True):
        if pa.types.is_nested(kind):
            raise TransformError(
                f"column {name!r} is {kind}, and a nested column has no "
                f"{target_format} {UNIT[target_format]} spelling; flatten it before converting"
            )
        if pa.types.is_binary(kind) or pa.types.is_large_binary(kind) or pa.types.is_fixed_size_binary(kind):
            raise TransformError(
                f"column {name!r} holds raw bytes, which have no JSON spelling; decode or drop it before converting"
            )
    return [{key: _spelled(value) for key, value in row.items()} for row in table.to_pylist()]


def _spelled(value: object) -> JsonValue:
    """Give one arrow value its JSON spelling, in the one house conversion."""
    try:
        return spelled(value)
    except ValueError as error:
        # A schema check above rules out nested and binary columns, so nothing else arrives.
        raise TransformError(str(error)) from error


def _read_text(source: bytes, source_format: str, target_format: str) -> list[dict[str, JsonValue]]:
    """Read the sequence of records a text format spells out, refusing rows that nest."""
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TransformError(
            f"the input is not UTF-8 text: {error.reason} at byte {error.start}; a text format is UTF-8"
        ) from error
    if source_format == "csv":
        return _read_csv(text)
    values = _read_json_values(text, source_format, target_format)
    records: list[dict[str, JsonValue]] = []
    for number, value in enumerate(values, start=1):
        if not isinstance(value, dict):
            raise TransformError(
                f"{UNIT[source_format]} {number} of the input is not an object, and a parquet row is a flat object"
            )
        records.append(value)
    return records


def _read_json_values(text: str, source_format: str, target_format: str) -> list[JsonValue]:
    """Read a JSON array, or one JSON value per line, the way convert.std reads them."""
    if source_format == "json":
        try:
            parsed: JsonValue = json.loads(text)
        except ValueError as error:
            raise TransformError(f"the input is not JSON: {error}") from error
        if not isinstance(parsed, list):
            raise TransformError(
                f"json to {target_format} writes one {UNIT[target_format]} per element, "
                f"so the input has to be a JSON array"
            )
        return parsed
    values: list[JsonValue] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            values.append(json.loads(line))
        except ValueError as error:
            raise TransformError(f"line {number} of the input is not JSON: {error}") from error
    return values


def _read_csv(text: str) -> list[dict[str, JsonValue]]:
    """Read the header row and its rows, as objects whose every value is a string."""
    rows = csv.reader(io.StringIO(text, newline=""))
    header = next(rows, None)
    if header is None:
        return []
    _check_header(header)
    records: list[dict[str, JsonValue]] = []
    for number, row in enumerate(rows, start=1):
        if not row:
            continue
        if len(row) > len(header):
            raise TransformError(
                f"row {number} of the csv has more cells than the header names columns, "
                f"and a cell no column names has nowhere to go"
            )
        records.append({name: row[index] if index < len(row) else "" for index, name in enumerate(header)})
    return records


def _columns_phrase(positions: list[int]) -> str:
    """Word one or more column positions, counting from one."""
    listed = ", ".join(str(position) for position in positions)
    return f"column {listed}" if len(positions) == 1 else f"columns {listed}"


def _check_header(header: list[str]) -> None:
    """Refuse a header that leaves a name empty or repeats one.

    A record key names its column, so neither has a record spelling: keeping one of two
    columns that share a name, or keying a column by the empty string, drops content while
    reporting success.
    """
    positions: dict[str, list[int]] = {}
    for index, name in enumerate(header, start=1):
        positions.setdefault(name, []).append(index)
    unnamed = positions.pop("", None)
    if unnamed is not None:
        raise TransformError(
            f"the csv header has no name at {_columns_phrase(unnamed)}, and a record key names "
            f"its column; name it before converting"
        )
    repeated = [(name, where) for name, where in positions.items() if len(where) > 1]
    if repeated:
        listed = "; ".join(f"{name!r} at {_columns_phrase(where)}" for name, where in repeated)
        raise TransformError(
            f"the csv header repeats a column name: {listed}; a record key names one column, "
            f"so rename them before converting"
        )


#: The arrow type each column kind writes as. A column every row leaves null carries no
#: kind at all and is written as a nullable string column.
KIND_TYPES: Final[dict[str, pa.DataType]] = {
    "boolean": pa.bool_(),
    "integer": pa.int64(),
    "number": pa.float64(),
    "string": pa.string(),
}


def _write_parquet(records: list[dict[str, JsonValue]]) -> bytes:
    """Infer one type per column from the records, then write them as parquet bytes."""
    schema = pa.schema([(name, KIND_TYPES[kind]) for name, kind in _columns(records).items()])
    sink = io.BytesIO()
    pq.write_table(pa.Table.from_pylist(records, schema=schema), sink)  # pyright: ignore[reportUnknownMemberType]
    return sink.getvalue()


def _columns(records: list[dict[str, JsonValue]]) -> dict[str, str]:
    """Name each column's one kind, refusing a column whose rows disagree.

    Integers and floats unify to a float column, because JSON calls both a number; any
    other mix is two types in one column, which parquet does not write and a codec that
    coerced would not preserve.
    """
    kinds: dict[str, str] = {}
    for number, record in enumerate(records, start=1):
        for key, value in record.items():
            kind = _kind(value, number, key)
            if kind is None:
                continue
            settled = kinds.get(key)
            if settled is None:
                kinds[key] = kind
            elif {settled, kind} == {"integer", "number"}:
                kinds[key] = "number"
            elif settled != kind:
                raise TransformError(
                    f"column {key!r} holds both {settled} and {kind} values, and a parquet "
                    f"column carries one type; reshape it before converting"
                )
    for key in {name for record in records for name in record}:
        kinds.setdefault(key, "string")
    return kinds


def _kind(value: JsonValue, number: int, key: str) -> str | None:
    """Name one value's column kind, refusing the nested ones parquet is not asked to hold."""
    if value is None:
        return None
    if isinstance(value, dict | list):
        raise TransformError(
            f"row {number} has a nested value at {key!r}, and this codec writes flat "
            f"columns; flatten it before converting"
        )
    # Before the integer check, because a bool is an int in Python and is not one in JSON.
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "string"


def _write_text(records: list[dict[str, JsonValue]], target_format: str) -> str:
    """Write the records in a text spelling, the way convert.std writes them."""
    if target_format == "json":
        return json.dumps(records, separators=(",", ":"))
    if target_format == "ndjson":
        return "".join(f"{json.dumps(record, separators=(',', ':'))}\n" for record in records)
    return _write_csv(records)


def _write_csv(records: list[dict[str, JsonValue]]) -> str:
    """Write a header of every key any row has, in first-seen order, and one row per record."""
    header: list[str] = []
    for record in records:
        header.extend(key for key in record if key not in header)
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for record in records:
        writer.writerow([_cell(record.get(key)) for key in header])
    return out.getvalue()


def _cell(value: JsonValue) -> str:
    """Render one value as csv text. Reading ruled the nested ones out already."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)
