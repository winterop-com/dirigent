# jq

Three of the four transform engines run jq programs -- `transform.jq` for a whole-value
reshape, `map.jq` once per element, `filter.jq` as a per-element yes or no. What each block
takes and promises is the [transforms page](transforms.md); this page is the language the
programs are written in, taught on the shapes a pipeline actually moves.

jq is worth learning here because it is the reshape that costs nothing: a program is handed
a value and returns values, opens no file, no socket, starts no process, and so runs with no
allowlist entry on any worker. The whole language fits in an afternoon; the working set
below fits in this page.

## How a program runs here

The engines run [jq 1.8](https://jqlang.org/manual/v1.8/) and keep its semantics, with the
differences a program author has to know:

| Upstream jq | Here |
| --- | --- |
| A program is a stream and may emit any number of outputs. | `transform.jq` makes one value of them: one output is the value, several become a list in emission order, and **none fails the step as rejected** -- a program that means "possibly nothing" says `[]` or `null`, never `empty`. `map.jq` and `filter.jq` demand exactly one output per element. |
| `env` and `$ENV` read the process environment. | Both read an empty object. The worker's environment is where dirigent's own secrets live, and a parameter or a connection is how a pipeline is handed a value. |
| A broken program errors when it runs. | A program that does not compile is refused when the document is applied, with jq's own message. One that compiles and meets the wrong data fails the attempt as rejected -- retrying would meet the same data again. |
| `input`, `--arg`, and the rest of the command line | There is no command line and there are no files: the program's one input is the step's `input` or `input_uri`, and its arguments arrive by composing them into that input (the join example below). |

## A value in, values out

Every example below reads the same input, a list of station readings:

```json
[{"station": "st-1", "region": "east", "celsius": 12, "status": "active"},
 {"station": "st-2", "region": "west", "celsius": -3, "status": "active"},
 {"station": "st-3", "region": "east", "celsius": 7,  "status": "down"}]
```

`.` is the input itself. `.region` reads a field, `.readings[0].station` reaches through
nesting, and `.[]` turns a list into a stream of its elements -- the sentence most programs
start with:

```text
.[] | .station              =>  "st-1", "st-2", "st-3"
```

Three outputs, not a list of three: a stream. Wrap a stream in `[...]` to make it a list
again. The difference matters here more than upstream, because of the table above: a
`transform.jq` program that ends as a stream gets its outputs collected into a list, and one
that ends as an empty stream fails the step. `[.[] | ...]` says "a list, possibly empty" and
is almost always what a reshape means.

## Pipes and shapes

`|` feeds the output of one filter to the next, exactly as in a shell:

```text
.celsius * 9 / 5 + 32 | round        =>  54
```

`{...}` builds an object. A bare field name copies it, and a computed value takes an
expression:

```text
{station, fahrenheit: (.celsius * 9 / 5 + 32 | round)}
    =>  {"station": "st-1", "fahrenheit": 54}
```

Those two pieces compose into the pattern `examples/transform/jq-reshape.yaml` is built on
-- iterate, keep, shape, collect:

```text
[.[] | select(.status == "active") | {station, celsius}]
    =>  [{"station": "st-1", "celsius": 12}, {"station": "st-2", "celsius": -3}]
```

## Keeping and mapping

`select(condition)` passes its input through when the condition holds and emits nothing when
it does not. `map(f)` applies `f` to every element of a list and is `[.[] | f]` spelled as
one word:

```text
map(.celsius)                        =>  [12, -3, 7]
```

When the *step* is element-wise, say so with the block instead of the program: a `filter.jq`
step is `select` as a contract (the program answers `true` or `false`, the frame keeps or
drops the untouched element), and a `map.jq` step is `map` as a contract (one output per
element, length preserved). A program that filters inside a `map.jq` step is refused by the
frame -- the [verb table](transforms.md#verbs-and-kinds) is the map of which block means
what.

## Absent and wrong

`//` answers with its right side when the left is `null` or missing:

```text
.name // "unnamed"                   =>  "unnamed"
```

It also fires on `false`, which is the classic trap: `.enabled // true` can never say
`false`. For booleans, ask `has("enabled")` or compare explicitly.

`?` suppresses an error from the access it is attached to, and parenthesising picks how much
it guards -- `(.properties.value)?` emits nothing when `.properties` is a string, where
`.properties.value?` would still error. `try f catch g` is the explicit spelling:

```text
try tonumber catch null              =>  12 for "12", null for "st-1"
```

Remember the stream rule: `(.x)?` emitting *nothing* in a `transform.jq` step whose whole
program it is fails the step. `(.x)? // null` says "or null" and survives.

## Words

Strings interpolate with `\(...)`, and the usual verbs are all present:

```text
"\(.station): \(.celsius)C"          =>  "st-1: 12C"
"east,west" | split(",")             =>  ["east", "west"]
map(.region) | unique | join(" and ") =>  "east and west"
.station | gsub("-"; "_")            =>  "st_1"
.station | capture("st-(?<n>[0-9]+)") | .n | tonumber   =>  1
```

`tostring` and `tonumber` cross between words and numbers; `@csv`, `@tsv` and `@json` render
a row when a downstream step wants text rather than structure (though `convert.std` is the
codec for whole documents).

## Grouping and aggregating

`group_by` sorts and buckets by a key; the aggregate verbs then read each bucket:

```text
group_by(.region) | map({region: .[0].region, stations: length})
    =>  [{"region": "east", "stations": 2}, {"region": "west", "stations": 1}]
```

`add`, `length`, `unique`, `min_by`/`max_by` cover most summaries without a loop:

```text
{stations: length, regions: (map(.region) | unique), warmest: (max_by(.celsius) | .station)}
    =>  {"stations": 3, "regions": ["east", "west"], "warmest": "st-1"}
map(.celsius) | add / length         =>  5.333333333333333
```

`reduce` is the loop when one is genuinely needed -- an accumulator threaded through a
stream:

```text
reduce .[] as $r (0; . + $r.celsius)  =>  16
```

`examples/transform/jq-group-and-aggregate.yaml` is the worked pipeline.

## Variables and joins

`. as $x` names the input so a later part of the program can still see it after the pipe has
moved on, and destructuring names parts of it:

```text
. as {$region, $rows} | [$rows[] | select(.region == $region)] | length   =>  2
```

That is also how a program takes arguments: compose them into the input in the step's
config, then destructure. Two upstream outputs become one join input the same way, and
`INDEX` builds the lookup table -- the heart of
`examples/transform/jq-join-two-sources.yaml`:

```text
. as {$stations, $readings}
| ($stations | INDEX(.id)) as $by_id
| [$readings[] | . + {name: ($by_id[.station].name // null)}]
```

A reading whose station is not in the index gets `name: null` rather than an error, because
the `//` said so.

## Many, none, and conditions

`range(n)` emits a stream of numbers, which is how a program manufactures data:

```text
[range(3) | {station: "st-\(.)"}]
    =>  [{"station": "st-0"}, {"station": "st-1"}, {"station": "st-2"}]
```

`if .celsius < 0 then "freezing" else "above zero" end` branches; `to_entries` turns an
object into rows and `del(.status)` drops a field; `. + {checked: true}` merges one object
over another:

```text
to_entries | map({name: .key, value})
    =>  [{"name": "east", "value": 2}, {"name": "west", "value": 1}]  for {"east": 2, "west": 1}
```

## The reference shelf

The engines embed jq 1.8.2, so [the jq 1.8 manual](https://jqlang.org/manual/v1.8/) is the
authoritative long tail. The working set, by what a program is doing:

| Doing | Builtins |
| --- | --- |
| Selecting | `.foo`, `.foo?`, `.[]`, `select`, `first`, `last`, `has`, `in`, `any`, `all` |
| Reshaping | `map`, `map_values`, `to_entries`, `from_entries`, `with_entries`, `del`, `paths`, `getpath`, `setpath`, `+` (merge), `*` (deep merge) |
| Aggregating | `add`, `length`, `group_by`, `unique`, `unique_by`, `sort_by`, `min_by`, `max_by`, `flatten`, `reduce`, `foreach`, `range` |
| Words | `"\(...)"`, `split`, `join`, `ltrimstr`, `rtrimstr`, `startswith`, `endswith`, `test`, `capture`, `sub`, `gsub`, `ascii_downcase`, `tostring`, `tonumber`, `@csv`, `@tsv`, `@json` |
| Absence and control | `//`, `?`, `try`/`catch`, `if`/`elif`/`else`/`end`, `not`, `empty`, `error` |
| Variables and joins | `. as $x`, `. as {$a, $b}`, `INDEX`, `IN` -- and `input` never answers, because a program has exactly one input |

Every program on this page runs against the printed input and produces the printed output.
The five `jq-` documents in
`examples/transform/` are the same language exercised end to end, each one runnable with
`dg run --local` and no allowlist entry.
