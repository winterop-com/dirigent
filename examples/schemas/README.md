# Example schemas

Each file here is a plain JSON Schema (Draft 2020-12): the shape a read is expected to return,
written down once so a pipeline can be refused the moment a payload moves out from under it. A
schema is **locally authored** -- a picture you hold of the payload, never something fetched or
introspected from the source. Each is applied on its own with `dg schema create`, or with the
directory it sits in, and a document that references one names it in `requires.schemas`. A document may instead **carry** a
schema in its own top-level `schemas:` section for a standalone or `--local` run; a server
refuses a document that carries one, so a shared instance holds its schemas here.

Apply one the way a person would:

```bash
dg schema create examples/schemas/dhis2-org-units.json
```

A directory apply lands them the same way: a server pointed at a directory stores every schema
it finds there before the pipelines, so a mounted corpus needs no separate step.

A schema carries its own identity in its keywords, so there is nothing else to pass:

- `$id` becomes the `code` the schema is addressed by (falling back to the file's stem).
- `title` becomes its name.
- `description` becomes its body.

| File | The shape it pins |
| --- | --- |
| [ou-record.json](ou-record.json) | A single organisation-unit record: a string `id`, a `name`, and an integer `level` |
| [dhis2-org-units.json](dhis2-org-units.json) | An object with an `organisationUnits` array of UID/name/level items |
| [dhis2-data-elements.json](dhis2-data-elements.json) | A `dataElements` array whose `valueType` and `domainType` are held to the DHIS2 enums |
| [dhis2-number-data-elements.json](dhis2-number-data-elements.json) | A `dataElements` array whose every `valueType` is `NUMBER` |
| [dhis2-system-info.json](dhis2-system-info.json) | A top-level object, not a list: an instance `version` and a `serverDate` |

The DHIS2 schemas pin the `fields=` reads the DHIS2 series makes, and `ou-record` is the shape
the two shape documents check a payload against. The [JSON Schema
guide](../../docs/json-schema.md) walks through how a schema like these is built, keyword by
keyword.
