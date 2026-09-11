# Transform examples

These pipelines reshape data with the transform verbs -- `transform`, `map`, `filter` and
`convert` -- which run a program or a codec against a value and execute nothing on the
worker. None of them needs an allowlist entry, a network, or anything installed first.
[docs/transforms.md](../../docs/transforms.md) is the page behind them: a verb is a contract
with a promise its frame enforces, and a kind is the engine that keeps it.

A file that stars an engine is prefixed with its kind, the way a block id's
`<verb>.<kind>` names it: `jq-` for the jq engines, `std-` for the `convert.std` codec. The
rest are named for the format they round-trip.

```bash
dg run --local examples/transform/jq-reshape.yaml
```

## Pipelines

| File | What it teaches |
| --- | --- |
| [jq-reshape.yaml](jq-reshape.yaml) | The whole-value reshape: one jq program between steps, then a fan-out that reads its list once per element. |
| [jq-filter-and-map.yaml](jq-filter-and-map.yaml) | The two element-wise verbs against the whole-value one: a subset, a list of the same length, and a reshape. |
| [jq-group-and-aggregate.yaml](jq-group-and-aggregate.yaml) | `group_by` and arithmetic: per-group sums and means with a total beside them. |
| [jq-join-two-sources.yaml](jq-join-two-sources.yaml) | Two upstream outputs composed into one inline input, joined with `INDEX`, unmatched rows kept with a null name. |
| [jq-stream-through-storage.yaml](jq-stream-through-storage.yaml) | The two doors on storage: `storage.write` puts a value in an object and `storage.read` brings one back, with the reshape between them. |
| [std-convert-fan-out.yaml](std-convert-fan-out.yaml) | The codec: csv to json, reshaped with jq, fanned out over the regions, and written back as csv. |
| [csv-report.yaml](csv-report.yaml) | Records shaped into flat rows and written as a csv artifact, with nothing on the allowlist. |
| [ndjson-round-trip.yaml](ndjson-round-trip.yaml) | ndjson: a JSON array re-spelled one record per line, and read back. |
| [yaml-config-to-json.yaml](yaml-config-to-json.yaml) | yaml: one document is one value, so a config becomes the object it describes, and comes back a document. |
| [xml-feed-to-ndjson.yaml](xml-feed-to-ndjson.yaml) | xml: a feed's elements as one record per line, the mapping that makes attributes and children keys, and the whole document as one object. |
| [parquet-round-trip.yaml](parquet-round-trip.yaml) | Records to parquet and back, the types surviving where csv would flatten them to strings (needs `dirigent-parquet`). |

Every program on this shelf is reference-free, so jq compiles them when the document is
applied and a syntax error is an issue beside every other one the document has. That is why
the data is always the step's `input` and never spliced into the program: a config carrying
a `${...}` cannot be checked until the run.
