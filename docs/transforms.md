# Transforms

Reshaping data between two steps is the most ordinary thing a pipeline does, and for a long
time the only way to do it here was `shell.run` behind the unsafe-block allowlist: a whole
subprocess, and a permission a person should not have to grant to uppercase a field.

A transform is the answer, and it is deliberately not one blessed language. It is a small set
of **verb contracts**, each implemented by pluggable **engine kinds**.

## Verbs and kinds

A transform block's id is `<verb>.<kind>`.

- The **verb** is the contract and its semantic promise. It says what the block does to a
  value, in a way that holds for every engine that implements it, and the shared frame is
  what enforces it.
- The **kind** is the engine: the thing that actually does the reshaping, and the thing a
  plugin package contributes.

So `transform.jq` and `transform.js` keep the same promise about their input and their
output, differ only in the language their program is written in, and are two ordinary block
ids in the same flat namespace as `http.request`. The allowlist, the catalog, `requires`, and
plugin contribution all work off machinery that already exists, because a transform block is
an operator like any other.

Four verbs are defined:

| Verb | The promise |
| --- | --- |
| `transform` | An arbitrary whole-value reshape, driven by a program. |
| `convert` | A content-preserving re-encoding, x to y. A codec: there is no program. |
| `map` | Element-wise: the output has the same length as the input. |
| `filter` | The output is a subset of the input, elements unmodified. |

All four have frames, and the frame is what enforces the promise: `map` builds its output
one element at a time and checks the length afterwards, and `filter` keeps the element it
was handed rather than anything the engine produced. An engine cannot break a promise the
frame keeps for it.

!!! note "Four engines ship"

    All four verbs ship with a jq engine -- `transform.jq`, `map.jq` and `filter.jq` -- and
    `convert.std` is the one codec. All four are installed with the built-in block pack, and
    none of them needs an allowlist entry. [The block reference](blocks.md) is generated from
    the live catalog, so it is the honest answer to "what can I actually run".

## What every transform takes

The frame owns the config every engine shares, so the fields below mean the same thing
whatever the verb and whatever the kind:

| Field | What it is |
| --- | --- |
| `input` | The value to work on, written inline in the document. |
| `input_uri` | A storage URI to read it from instead. |
| `save_to` | A storage URI to stream the result to, instead of carrying it inline. |
| `max_input` | How much of `input_uri` is read into memory. Defaults to 32mb, the same bound `http.request` puts on a body it holds. |

Exactly one of `input` and `input_uri` is required. Writing both, or neither, is refused at
apply rather than on the first run.

`examples/transform/` is the worked corpus for all of it: eleven documents, each prefixed with
the engine kind that stars in it, every one of them running with no network and nothing on the
allowlist. The README in that directory says which teaches what.

A worked step, with `transform.<kind>` standing in for the engine you name:

```yaml
steps:
  reshape:
    block: transform.<kind>
    depends_on: [fetch]
    config:
      # The upstream step's body, already in storage: it is streamed in rather than
      # inlined into this step's config, so a large document costs nothing to reference.
      input_uri: ${steps.fetch.output.body_uri}
      program: |
        .features | map({id: .id, value: .properties.value})
      # Without save_to the reshaped value is the step's output, and the engine spills a
      # large one to an artifact on its own. With it, the output carries the URI instead.
      save_to: ${run.scratch}/reshaped.json
```

Each verb adds the fields its own contract needs, and nothing else: `transform` adds
`program`, the text the engine's kind compiles, and `convert` adds `from` and `to`, the two
format names the engine trades between. A `convert` step therefore has no program at all:

```yaml
steps:
  as_csv:
    block: convert.<kind>
    depends_on: [reshape]
    config:
      input_uri: ${steps.reshape.output.output_uri}
      from: json
      to: csv
      save_to: ${run.scratch}/rows.csv
```

The output is one of two shapes, and which one it is depends only on `save_to`:

- Without it, the reshaped value is the output (`value` for `transform`, `text` for
  `convert`), and downstream steps reference it directly.
- With it, the output carries `output_uri` and `output_bytes`, and a downstream step reads
  from storage. A result worth saving is a result the next step reads from storage.

An input larger than `max_input` is refused rather than truncated: half a document is not a
smaller input, it is a wrong one.

## `transform.jq`

The engine that ships with the built-in pack. Its program is a [jq](https://jqlang.org)
program -- [the jq page](jq.md) teaches the language on this corpus -- and the value it is
handed is the input:

```yaml
steps:
  reshape:
    block: transform.jq
    depends_on: [fetch]
    config:
      input_uri: ${steps.fetch.output.body_uri}
      program: |
        [.readings[] | select(.status == "active") | {station, region, celsius}]
```

A jq program is a stream rather than a function, so it may emit any number of outputs, and
the step's output says exactly what the stream said:

| The program emitted | The step's `value` |
| --- | --- |
| One output | That value. |
| Several outputs | The list of them, in the order jq produced them. |
| Nothing | Nothing: the step fails as rejected. |

The last row is the only one that is a decision. A step has to produce an output for the next
step to read, so a program that produced none is refused rather than passing a `null` on as
though it had meant to. A program that genuinely means "possibly nothing" says so: `[]` and
`null` are outputs, and `empty` is not.

A program jq cannot compile is refused when the document is applied, with jq's own message
about it rather than a paraphrase, because that message is what tells the author where the
program is wrong:

```text
invalid  daily-load  (pipelines/daily-load.yaml)
  - steps.reshape.config: jq: error: syntax error, unexpected end of file at <top-level>,
    line 1, column 7
```

A program that compiles and then meets the wrong data -- indexing a string, adding a null --
fails the attempt as rejected with jq's runtime message, and retrying it would only produce
the same message again.

jq opens no file, no socket, and starts no process: it is handed a value and returns values.
So `transform.jq` is not code execution on the worker, declares no `local_execution`, and
needs no entry in `DIRIGENT_ENABLED_UNSAFE_BLOCKS`. That is the whole point of the engine:
the reshape that used to cost an instance an allowlisted `shell.run` now costs it nothing.

The one thing stock jq reads that is not its input is the process environment, through `env`
and `$ENV`, and the worker's environment is where dirigent's own secrets live. Both are
shadowed: a program sees an empty object, exactly as `env_allowlist` refuses `DIRIGENT_*` to
`shell.run`. A pipeline that needs a value from the environment is handed it as a parameter
or a connection, which is what those are for.

`examples/transform/jq-reshape.yaml` is the worked pipeline, and it runs with no network and
no allowlist: one reshape, a fan-out that reads the reshaped list once per element, and a
step that reads the whole fan back.

```bash
dg run --local examples/transform/jq-reshape.yaml
```

## `map.jq`

Element-wise: the program is run once per element of a list, with that element as its input,
and the element it produces takes its place.

```yaml
steps:
  fahrenheit:
    block: map.jq
    depends_on: [active]
    config:
      input: ${steps.active.output.value}
      program: |
        {station, region, fahrenheit: (.celsius * 9 / 5 + 32 | round)}
```

**The output has one element for every element of the input, in input order.** That is the
verb's promise and the frame is what keeps it: the frame reads the input as a list, calls the
engine once per element, and collects the results, so the length is equal by construction. It
asserts it again afterwards, so an engine that reached past the loop fails itself with its own
id in the message rather than quietly returning a shorter list.

An input that is not a JSON array is refused, naming what arrived:

```text
map.jq replaces every element of a list, so its input has to be a JSON array, and this one
is an object
```

A program that fails on one element fails the step, and the failure names the element by its
0-based index, because the eleventh element of a list of five hundred is otherwise a hunt:

```text
element 11: jq: error: Cannot index string with "celsius"
```

The per-element contract is exactly one output. A jq program is a stream, and for a map that
stream has to be one thing: zero outputs would shorten the list and several would lengthen it,
and both are refused with the verb that does want them:

```text
element 0: the program produced 0 outputs, and a map replaces an element with exactly one; a
program that drops elements is a filter.jq step, and one that changes how many there are is a
transform.jq step
```

## `filter.jq`

The program is run once per element and answers one question about it: keep it, or not.

```yaml
steps:
  active:
    block: filter.jq
    config:
      input_uri: ${steps.fetch.output.body_uri}
      program: |
        .status == "active"
```

**The output is a subset of the input, and the elements are unmodified.** That promise is
structural rather than a rule an engine is asked to follow: the engine answers `true` or
`false` and the frame appends the element *it* was given, never anything the engine returned,
so an engine has no way to edit an element it was only asked about. Order is the input's.

An input that is not a JSON array is refused the same way a map's is:

```text
filter.jq keeps some of the elements of a list, so its input has to be a JSON array, and this
one is a string
```

The answer has to be exactly one output, and that output has to be `true` or `false`.
**jq's truthiness is not applied.** A program yielding `0`, `""` or `null` is a mistake
surfaced, not an element quietly dropped, so an author who means "has readings" writes it:

```text
element 0: the program answered 4, and a filter answers true or false; jq's truthiness is not
applied, so a program meaning 'has readings' writes '.count > 0'
```

```text
element 0: the program produced 0 outputs, and a filter answers one true or false per element;
a program that reshapes an element is a map.jq or transform.jq step
```

Both engines are sandboxed exactly as `transform.jq` is -- `env` and `$ENV` read an empty
object -- and neither executes code on the worker, so neither needs an allowlist entry.

`examples/transform/jq-filter-and-map.yaml` is the worked pipeline: the active readings kept, each one
converted, and a whole-value reshape after them, which is the line between the three verbs
drawn in one document.

```bash
dg run --local examples/transform/jq-filter-and-map.yaml
```

## `convert.std`

The codec that ships with the built-in pack, on the standard library and nothing else. It
converts between five formats, along the thirteen pairs it declares:

| From | To | What it does |
| --- | --- | --- |
| `json` | `ndjson` | The source is one JSON array; each element becomes one line. |
| `json` | `csv` | The source is one JSON array of flat objects; each element becomes one row. |
| `ndjson` | `json` | The lines become one array. Blank lines are skipped. |
| `ndjson` | `csv` | The lines become the rows, on the same terms as `json` to `csv`. |
| `csv` | `json` | An array of objects keyed by the header row. |
| `csv` | `ndjson` | Those same objects, one per line. |
| `yaml` | `json` | One YAML document as the one value it holds. |
| `json` | `yaml` | One JSON value as one YAML document, in block style. |
| `yaml` | `ndjson` | A YAML stream: each `---` document becomes one line. |
| `ndjson` | `yaml` | Each line becomes one document of a YAML stream. |
| `xml` | `json` | One object keyed by the root element's tag, by the mapping below. |
| `json` | `xml` | An object of one key, written back out as the document that key names the root of. |
| `xml` | `ndjson` | The root's children as the records, one line each, streamed. |

json, ndjson and csv say the same thing -- a sequence of records -- so a conversion is reading
that sequence out of one spelling and writing it in another. Everything the engine refuses
is a source that is not that sequence: a JSON value that is not an array, a line that is not
JSON, named by its 1-based line number, or bytes that are not UTF-8, named by the byte that
is not. Encoding is UTF-8 in both directions.

```yaml
steps:
  parse:
    block: convert.std
    depends_on: [fetch]
    config:
      input_uri: ${steps.fetch.output.body_uri}
      from: csv
      to: json
```

**Every cell read out of a csv is a string.** A csv carries no types: `4.5` in a cell is the
three characters, and a codec that decided it was a number would be guessing, on a column
where `007` is a code and `1-2` is a range. So `csv` to `json` produces `"4.5"`, and a
pipeline that wants the number says so in the step that follows -- `tonumber` in a jq
program is one character of typing and the only place that knows the column.

**The csv header is the union of the keys the rows have, in first-seen order.** A key only
the third row carries is still a column, and the rows without it have an empty cell there. A
header taken from the first row alone would silently drop data.

**A nested value has no csv spelling, so it is refused**, naming the row and the key. Writing
`{"region": "east"}` into a cell as text is not the same content, and a codec that does it
has stopped being a codec. Flatten before converting: a list of stations becomes one joined
string in the step that knows what the separator should be. Values that do have a spelling
get their JSON one: a number is its digits, a boolean is `true` or `false`, and `null` is an
empty cell.

### yaml is a document or a stream

YAML spells two things, so the engine reads it two ways. **A YAML document is one value**, so
`yaml` and `json` trade one whole value in either direction: a config file becomes the object
it describes, and a JSON value comes back as one block-style document with its keys in the
order they arrived. **A YAML stream is many documents**, so `yaml` and `ndjson` trade one
document per line, each written with its `---`. A stream of more than one document is refused
on the way to `json`, naming how many arrived and saying that ndjson is where they go.

**A YAML value JSON has no word for is refused, naming its path.** An unquoted `2026-03-01`
is a date and not a string, and the rest of the list is the same shape: a timestamp, a
`!!set`, a `!!binary`, a node under a tag of your own, a mapping key that is not a string,
and `.nan` or `.inf`. Each is refused at `$.retention.before` rather than converted, because
deciding what text a date meant is the kind of guess a codec does not make. Quote it in the
source and it converts as the text it is.

### xml is one root element, and one mapping

An element is an object, and four rules make it reversible:

| In the document | In the object |
| --- | --- |
| an attribute | a key prefixed with `@` |
| the text of an element with no children | the value itself, a string |
| the text of an element that has attributes | the `#text` key beside them |
| a child element | a key of its tag |
| a tag that repeats | a list, in document order |

The `@` prefix is what closes the loop: `@` cannot start an XML name, so an attribute and a
child element of the same name never collide, and every key says which of the two it came
from. An empty element is `null`, a namespaced tag keeps ElementTree's `{uri}local` spelling,
and everything read out of an element is text exactly as it is out of a csv. **Mixed content
-- text sitting beside child elements -- is refused naming the element**, because the mapping
has nowhere to put it. `json` to `xml` therefore takes an object of exactly one key, which
names the root element, and refuses an empty array, an object holding both `#text` and child
keys, and a key that is no XML name, each naming its path.

`xml` to `ndjson` is the streaming direction: the root's children are the records, read with
`iterparse` and dropped as they are written, so a feed far larger than the records it holds
converts. It is one-way. An ndjson line carries no root element name to write a document
under, so `json` to `xml` is the pair that round-trips, and a document is named there.

**No document type declaration is read, in any direction.** A DTD is where entities and the
files they name enter an XML document, so one is refused rather than parsed, and an entity
nothing declared has nothing to expand to.

A pair the engine has no codec for is refused when the document is applied, the same hook
that compiles a jq program, and the refusal names the thirteen pairs that do exist:

```text
invalid  daily-load  (pipelines/daily-load.yaml)
  - steps.parse.config: convert.std does not convert csv to xml (csv to json, csv to ndjson,
    json to csv, json to ndjson, json to xml, json to yaml, ndjson to csv, ndjson to json,
    ndjson to yaml, xml to json, xml to ndjson, yaml to json, yaml to ndjson)
```

`examples/transform/std-convert-fan-out.yaml` is the worked pipeline: an inline csv re-encoded as json, a
jq program reshaping it, a fan-out over the regions, and the result converted back to csv.
It runs with no network and no allowlist.

```bash
dg run --local examples/transform/std-convert-fan-out.yaml
```

`yaml-config-to-json.yaml` and `xml-feed-to-ndjson.yaml` are the other two on that shelf: the
first reads a config as the object it describes and writes it back as a document, the second
reads a feed as one record per line and then as one whole object.

```bash
dg run --local examples/transform/yaml-config-to-json.yaml
dg run --local examples/transform/xml-feed-to-ndjson.yaml
```

## `convert.arrow`

The parquet codec, shipped separately in `dirigent-parquet` because it stands on pyarrow
where `convert.std` deliberately stands on the standard library alone. Installing the pack
is what puts the block in the catalog. It trades parquet with the three text spellings, in
every direction:

| From | To | What it does |
| --- | --- | --- |
| `parquet` | `json`, `ndjson`, `csv` | Each row becomes one record, every value in its JSON spelling. |
| `json`, `ndjson`, `csv` | `parquet` | Each record becomes one row, under a schema inferred from the records. |

The record model is `convert.std`'s -- a sequence of flat records -- and the refusals
mirror it: a nested column has no flat spelling and is refused naming it, in either
direction. What parquet adds is types. Writing infers one type per column -- boolean,
int64, float64, or string -- and a column whose rows disagree is refused naming it rather
than coerced; integers and floats unify to a float column, because JSON calls both a
number. A csv source carries no types, so csv to parquet writes string columns. Reading
gives every value its JSON spelling: timestamps, dates and times come back as ISO strings,
decimals as strings, and a float that is NaN or infinite as null.

Parquet is bytes rather than text, so it always travels by uri: `input_uri` in, and
`save_to` required when parquet is the target. A config that writes a parquet payload
inline, or asks for one back inline, is refused at apply.

## Safety is per kind

The verb says nothing about safety; the engine does, and the gates it goes through are the
ones that already exist.

- An engine that compiles a program and evaluates it against a value, executing no code on
  the worker, is not code execution. A `jq` kind needs no allowlist entry, and a document
  using it applies and runs like `http.request` does.
- An engine that runs a language runtime -- a `js` kind on bun, say -- **is** code execution.
  It declares itself as such, which puts it behind `DIRIGENT_ENABLED_UNSAFE_BLOCKS` exactly
  like `shell.run`, and both the apply check and the execution path refuse it where an
  instance has not allowed it.
- A `convert` kind is a codec rather than a language, so the question does not arise. It
  declares the format pairs it supports and nothing else.

Whatever the kind, an engine is handed a value and returns a value. It touches no HTTP, no
file outside storage, and nothing in the environment: reading the input and writing the
output are the frame's job, not the engine's.

## A bad program is refused at apply

Blocks may refuse a config for reasons their published JSON Schema cannot express, and a
transform is the clearest case: the schema can say `program` is a string, and only the engine
can say the string is not a program.

That refusal happens where the blocks themselves live, which is the instance. `dg apply`
reports it as an issue at the step's config location, beside every other issue the document
has, and `$validate` reports it again for a version already stored, so an engine uninstalled
or upgraded under a pipeline is found before its next run:

```text
invalid  daily-load  (pipelines/daily-load.yaml)
  - steps.reshape.config: unexpected token ')' at position 14
```

The document is not stored, so it is never scheduled and never found to be unrunnable on the
first run at three in the morning. For a `convert` kind the same check refuses a format pair
the engine has no codec for, and says which pairs it does have.

One exception, and it is deliberate: a config still carrying a `${...}` reference is not known
at apply, so it is left to the run. A block asked to compile `${params.filter}` would refuse
the reference rather than the program.

## Writing an engine

An engine is a small class. It subclasses the frame for its verb, names its kind, and
supplies the part that is specific to it; the frame derives the block id, the spec, the
config model, the output model, `execute`, and the apply-time check.

A program engine supplies `compile` and `apply`:

```python
from pydantic import JsonValue

from dirigent_plugin import TransformError, Transformer


class CaseTransformer(Transformer):
    """Change the case of every string in a value."""

    kind = "case"
    summary = "Recase every string in a value."

    def compile(self, program: str) -> object:
        if program not in ("upper", "lower"):
            raise TransformError(f"{program!r} is not a case: write upper or lower")
        return program

    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        if isinstance(value, str):
            return value.upper() if compiled == "upper" else value.lower()
        return value
```

That is `transform.case`: the id is derived from the kind, the config gains `program`
beside the shared fields, and `compile` is what the apply-time check runs. Raising
`TransformError` is how an engine refuses; the frame turns it into a rejected issue at apply
and a rejected failure at run time, so an engine never classifies a failure itself. An engine
that runs a language runtime adds `local_execution = True`, which is the whole of putting
itself behind the allowlist.

A codec engine declares its pairs and supplies `convert`:

```python
from dirigent_plugin import Converter


class ParquetConverter(Converter):
    """Re-encode between parquet and the row formats the built-in codec already knows."""

    kind = "parquet"
    summary = "Convert between parquet, json, and ndjson."
    pairs = frozenset({("parquet", "json"), ("json", "parquet"), ("parquet", "ndjson")})

    def convert(self, source: bytes, *, source_format: str, target_format: str) -> bytes: ...
```

The frame refuses an unsupported pair before `convert` is ever called, at apply and again on
the worker, and the refusal names what the engine does support. Shipping `convert.parquet`
is therefore contributing one class from one package: nothing in the core learns the word.

A `map` engine and a `filter` engine are the same shape with the element-wise half swapped
in. `Mapper` supplies `compile` and `apply`, where `apply` is handed one element and returns
the element that replaces it; `Filterer` supplies `compile` and `keep`, which answers `True`
or `False` about one element and nothing else. Neither enforces its verb's promise, because
the frame does: the length equality and the untouched elements hold for every kind, including
one written badly.

Engines are contributed like any other block, in the plugin's `Contribution`, and
[the Python guide](python.md#testing-a-block) is how to test one -- `call_block` validates
the config the way the engine does and makes the call, and `check_config` is an ordinary
method a test calls directly.
