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
  version of the pipeline -- so a carried schema is for a standalone or `--local` run. Two
  examples here carry their schema.
- **A named instance schema.** The code names a schema the instance holds, applied on its own
  from [`../schemas/`](../schemas) with `dg schema create`. The document declares it under
  `requires.schemas`, so an instance that does not hold it refuses the document. A `--local`
  run holds no instance schema until one is handed to it with `--schema FILE`; each such
  document's top-of-file comment shows the invocation.

The DHIS2 documents read real metadata from the public play demo through a carried
connection; they only read, and each asks for a different `fields=` projection, so the schema
each validates against differs -- the projection and the schema are two spellings of one
expectation. Two pairs show the same shape supplied both ways: `expects-a-shape` carries
`ou-record` while `the-shape-is-wrong` names the instance `ou-record`, and
`dhis2-data-elements-carried` carries `dhis2-data-elements` while `dhis2-data-elements-named`
names the instance one.

| File | Technique | What it demonstrates |
| --- | --- | --- |
| [expects-a-shape.yaml](expects-a-shape.yaml) | schema carried in the document | A payload that fits: the gate passes it through, and the next step reads `${steps.check.output.value}`. |
| [the-shape-is-wrong.yaml](the-shape-is-wrong.yaml) | references the `ou-record` instance schema | A payload missing a required field: the run fails at the gate, naming the path, and the reader never runs. |
| [dhis2-org-units-shape.yaml](dhis2-org-units-shape.yaml) | references the `dhis2-org-units` instance schema | `fields=id,displayName,level` on organisation units, validated as an array of typed records. |
| [dhis2-data-elements-carried.yaml](dhis2-data-elements-carried.yaml) | schema carried in the document | `fields=id,name,valueType,domainType` on data elements, with the shape carried in the document. |
| [dhis2-data-elements-named.yaml](dhis2-data-elements-named.yaml) | references the `dhis2-data-elements` instance schema | The same check, against the schema the instance holds rather than a carried one. |
| [dhis2-numbers-only.yaml](dhis2-numbers-only.yaml) | references the `dhis2-number-data-elements` instance schema | A `filter` narrows the read to NUMBER-valued elements; the schema sharpens, proving none of another type slipped through. |
| [dhis2-system-info-shape.yaml](dhis2-system-info-shape.yaml) | references the `dhis2-system-info` instance schema | `/api/system/info` validated as a top-level object -- a schema needs no list to gate on. |
