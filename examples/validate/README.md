# Validation examples

A gate that fails at the boundary. `validate.schema` checks a value against a JSON Schema
and passes it through when it fits, so a step reads the gate's output rather than the raw
value and the graph records that everything past the gate received the right shape. A value
that does not fit is refused where it enters -- with the path into the payload that is
wrong -- rather than surfacing as a confusing error in a step further down. A mismatch is
`rejected`: the same value against the same schema fails the same way, so it is never
retried.

A gate never writes a schema inline: it names one by `code`. That code resolves one of two
ways, and each document below is labelled by which it uses:

- **Carried in the document.** The shape sits in the document's own top-level `schemas:`
  section, keyed by its code, exactly the way a document can carry its own `connections:`. A
  server refuses a document that carries a schema -- storing it would put the shape in every
  version of the pipeline -- so a carried schema is for a standalone or `--local` run.
- **A named instance schema.** The code names a schema the instance holds, applied on its own
  from [`../schemas/`](../schemas) with `dg schema create`. The document declares it under
  `requires.schemas`, so an instance that does not hold it refuses the document. A `--local`
  run holds no instance schema until one is handed to it with `--schema FILE`; each such
  document's top-of-file comment shows the invocation.

The two documents are one pair, showing the same shape supplied both ways: `expects-a-shape`
carries `ou-record` in the document, and `the-shape-is-wrong` names the instance `ou-record`
that [`../schemas/ou-record.json`](../schemas/ou-record.json) holds.

| File | Technique | What it demonstrates |
| --- | --- | --- |
| [expects-a-shape.yaml](expects-a-shape.yaml) | schema carried in the document | A payload that fits: the gate passes it through, and the next step reads `${steps.check.output.value}`. |
| [the-shape-is-wrong.yaml](the-shape-is-wrong.yaml) | references the `ou-record` instance schema | A payload missing a required field: the run fails at the gate, naming the path, and the reader never runs. |
