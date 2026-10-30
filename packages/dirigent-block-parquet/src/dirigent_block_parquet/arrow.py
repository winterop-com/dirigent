"""The ``arrow`` engine for the convert verb: parquet against the text formats, on pyarrow."""

import csv
import io
import json
from typing import Final

import pyarrow as pa
import pyarrow.parquet as pq
from pydantic import BaseModel, JsonValue

from dirigent_block_parquet.messages import (
    BINARY_COLUMN,
    CSV_HEADER_REPEATED,
    CSV_HEADER_UNNAMED,
    CSV_ROW_TOO_WIDE,
    LINE_NOT_JSON,
    MIXED_COLUMN,
    NESTED_COLUMN,
    NESTED_VALUE,
    NO_JSON_SPELLING,
    NOT_A_JSON_ARRAY,
    NOT_JSON,
    NOT_PARQUET,
    NOT_UTF8,
    RECORD_NOT_AN_OBJECT,
)
from dirigent_common import spelled
from dirigent_plugin import Converter, TransformError, csv_header, hold_csv_columns, hold_csv_empty_cells

#: The text spellings this engine trades parquet with.
TEXT_FORMATS: Final = ("json", "ndjson", "csv")

#: What a target format calls one element of the sequence it writes.
UNIT: Final = {"json": "element", "ndjson": "line", "csv": "row", "parquet": "row"}

#: How many rows a parquet is decoded at a time, so wide columns of nulls cost one batch to refuse.
READ_BATCH_ROWS: Final = 1024


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
    """

    kind = "arrow"
    summary = "Convert between parquet and the text formats."
    pairs = frozenset({("parquet", text) for text in TEXT_FORMATS} | {(text, "parquet") for text in TEXT_FORMATS})

    def convert(self, source: bytes, *, source_format: str, target_format: str) -> bytes:
        """Read the records out of the source format and write them in the target format."""
        if source_format == "parquet":
            records = _read_parquet(source, target_format)
        else:
            records = _read_text(source, source_format, target_format)
        if target_format == "parquet":
            return _write_parquet(records)
        return _write_text(records, target_format).encode()


def _read_parquet(source: bytes, target_format: str) -> list[dict[str, JsonValue]]:
    """Read a parquet payload as records, refusing what its footer already says the target cannot hold.

    The footer costs nothing to read and the pages may decode to far more than the payload's
    size, so everything it answers is asked before a page is read. A file written without
    statistics, or lying in them, is held to the same limit by counting as the batches arrive.
    """
    try:
        opened = pq.ParquetFile(pa.BufferReader(source))
    except pa.ArrowInvalid as error:
        raise TransformError(NOT_PARQUET.render(detail=str(error))) from error
    schema = opened.schema_arrow
    for name, kind in zip(schema.names, schema.types, strict=True):
        if pa.types.is_nested(kind):
            raise TransformError(
                NESTED_COLUMN.render(
                    column=repr(name), kind=kind, target_format=target_format, unit=UNIT[target_format]
                )
            )
        if pa.types.is_binary(kind) or pa.types.is_large_binary(kind) or pa.types.is_fixed_size_binary(kind):
            raise TransformError(BINARY_COLUMN.render(column=repr(name)))
    shape = _Shape(rows=opened.metadata.num_rows, columns=len(schema.names))
    if target_format == "csv":
        hold_csv_columns(shape.columns)
        shape.hold_empty(_declared_nulls(opened))
    records: list[dict[str, JsonValue]] = []
    empty = 0
    try:
        for batch in opened.iter_batches(batch_size=READ_BATCH_ROWS):  # pyright: ignore[reportUnknownMemberType]
            if target_format == "csv":
                empty += sum(batch.column(index).null_count for index in range(batch.num_columns))  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                shape.hold_empty(empty)
            records.extend({key: _spelled(value) for key, value in row.items()} for row in batch.to_pylist())
    except pa.ArrowInvalid as error:
        raise TransformError(NOT_PARQUET.render(detail=str(error))) from error
    return records


class _Shape(BaseModel):
    """How many rows and columns a parquet's footer declares."""

    rows: int
    columns: int

    def hold_empty(self, empty: int) -> None:
        """Refuse this shape as a csv once this many of its cells are known to be empty."""
        hold_csv_empty_cells(rows=self.rows, columns=self.columns, empty=empty)


def _declared_nulls(opened: pq.ParquetFile) -> int:
    """Add up the nulls a parquet's footer declares, counting a column chunk without statistics as none."""
    metadata = opened.metadata
    total = 0
    for group in range(metadata.num_row_groups):
        row_group = metadata.row_group(group)
        for column in range(row_group.num_columns):
            statistics = row_group.column(column).statistics
            total += (statistics.null_count if statistics is not None else None) or 0
    return total


def _spelled(value: object) -> JsonValue:
    """Give one arrow value its JSON spelling, in the one house conversion."""
    try:
        return spelled(value)
    except ValueError as error:
        # A schema check above rules out nested and binary columns, so nothing else arrives.
        raise TransformError(NO_JSON_SPELLING.render(detail=str(error))) from error


def _read_text(source: bytes, source_format: str, target_format: str) -> list[dict[str, JsonValue]]:
    """Read the sequence of records a text format spells out, refusing rows that nest."""
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TransformError(NOT_UTF8.render(reason=error.reason, position=error.start)) from error
    if source_format == "csv":
        return _read_csv(text)
    values = _read_json_values(text, source_format, target_format)
    records: list[dict[str, JsonValue]] = []
    for number, value in enumerate(values, start=1):
        if not isinstance(value, dict):
            raise TransformError(RECORD_NOT_AN_OBJECT.render(unit=UNIT[source_format], number=number))
        records.append(value)
    return records


def _read_json_values(text: str, source_format: str, target_format: str) -> list[JsonValue]:
    """Read a JSON array, or one JSON value per line, the way convert.std reads them."""
    if source_format == "json":
        try:
            parsed: JsonValue = json.loads(text)
        except ValueError as error:
            raise TransformError(NOT_JSON.render(detail=str(error))) from error
        if not isinstance(parsed, list):
            raise TransformError(NOT_A_JSON_ARRAY.render(target_format=target_format, unit=UNIT[target_format]))
        return parsed
    values: list[JsonValue] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            values.append(json.loads(line))
        except ValueError as error:
            raise TransformError(LINE_NOT_JSON.render(number=number, detail=str(error))) from error
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
            raise TransformError(CSV_ROW_TOO_WIDE.render(number=number))
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
        raise TransformError(CSV_HEADER_UNNAMED.render(columns=_columns_phrase(unnamed)))
    repeated = [(name, where) for name, where in positions.items() if len(where) > 1]
    if repeated:
        listed = "; ".join(f"{name!r} at {_columns_phrase(where)}" for name, where in repeated)
        raise TransformError(CSV_HEADER_REPEATED.render(listed=listed))


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
                raise TransformError(MIXED_COLUMN.render(column=repr(key), settled=settled, kind=kind))
    for key in {name for record in records for name in record}:
        kinds.setdefault(key, "string")
    return kinds


def _kind(value: JsonValue, number: int, key: str) -> str | None:
    """Name one value's column kind, refusing the nested ones parquet is not asked to hold."""
    if value is None:
        return None
    if isinstance(value, dict | list):
        raise TransformError(NESTED_VALUE.render(number=number, key=repr(key)))
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
    header = csv_header(records)
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
