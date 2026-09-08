# dirigent-parquet

The parquet format pack for dirigent: one codec, `convert.arrow`, trading parquet with the
three text spellings `convert.std` already trades between.

| From | To | What it does |
| --- | --- | --- |
| `parquet` | `json`, `ndjson`, `csv` | Each row becomes one record, every value in its JSON spelling. |
| `json`, `ndjson`, `csv` | `parquet` | Each record becomes one row, under a schema inferred from the records. |

The record model is `convert.std`'s: a sequence of flat records. What parquet adds is
types, and the codec is honest about them in both directions:

- **Writing** infers one type per column -- boolean, int64, float64, or string -- from the
  records. Integers and floats unify to a float column, because JSON calls both a number;
  any other mix is refused naming the column. A column every row leaves null is written as
  a nullable string column. A csv source carries no types, so csv to parquet writes string
  columns and nothing else.
- **Reading** gives every value its JSON spelling: timestamps, dates and times come back as
  ISO strings, decimals as strings, and a float that is NaN or infinite as null. A nested
  column, or one holding raw bytes, is refused naming it -- flattening is a reshape, and a
  reshape belongs to a jq step that knows what the flattening should mean.

Parquet is bytes rather than text, so it always travels by uri: `input_uri` in, and
`save_to` required when parquet is the target. The inline `input` field is for text
sources only, and a config that breaks either rule is refused at apply.

The pack ships separately because `convert.std` is deliberately on the standard library
and nothing else; this codec stands on [pyarrow](https://arrow.apache.org/docs/python/).
Nothing else in the workspace may depend on it.
