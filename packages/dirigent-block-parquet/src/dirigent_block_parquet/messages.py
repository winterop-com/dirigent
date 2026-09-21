"""Every refusal the parquet codec makes, catalogued under the ``parquet`` prefix.

A codec refusal reaches an attempt as ``plugin.transform_failed``: the convert frame owns
the failure, and the codec's sentence rides on it as the ``detail`` param.
"""

from dirigent_common import Catalogue

PARQUET = Catalogue("parquet")

NOT_PARQUET = PARQUET.define("not_parquet", "the input is not parquet: {detail}")

NESTED_COLUMN = PARQUET.define(
    "nested_column",
    "column {column} is {kind}, and a nested column has no {target_format} {unit} spelling; "
    "flatten it before converting",
)

BINARY_COLUMN = PARQUET.define(
    "binary_column",
    "column {column} holds raw bytes, which have no JSON spelling; decode or drop it before converting",
)

NO_JSON_SPELLING = PARQUET.define("no_json_spelling", "{detail}")

NOT_UTF8 = PARQUET.define(
    "not_utf8",
    "the input is not UTF-8 text: {reason} at byte {position}; a text format is UTF-8",
)

RECORD_NOT_AN_OBJECT = PARQUET.define(
    "record_not_an_object",
    "{unit} {number} of the input is not an object, and a parquet row is a flat object",
)

NOT_JSON = PARQUET.define("not_json", "the input is not JSON: {detail}")

NOT_A_JSON_ARRAY = PARQUET.define(
    "not_a_json_array",
    "json to {target_format} writes one {unit} per element, so the input has to be a JSON array",
)

LINE_NOT_JSON = PARQUET.define("line_not_json", "line {number} of the input is not JSON: {detail}")

CSV_ROW_TOO_WIDE = PARQUET.define(
    "csv_row_too_wide",
    "row {number} of the csv has more cells than the header names columns, "
    "and a cell no column names has nowhere to go",
)

CSV_HEADER_UNNAMED = PARQUET.define(
    "csv_header_unnamed",
    "the csv header has no name at {columns}, and a record key names its column; name it before converting",
)

CSV_HEADER_REPEATED = PARQUET.define(
    "csv_header_repeated",
    "the csv header repeats a column name: {listed}; a record key names one column, so rename them before converting",
)

MIXED_COLUMN = PARQUET.define(
    "mixed_column",
    "column {column} holds both {settled} and {kind} values, and a parquet "
    "column carries one type; reshape it before converting",
)

NESTED_VALUE = PARQUET.define(
    "nested_value",
    "row {number} has a nested value at {key}, and this codec writes flat columns; flatten it before converting",
)
