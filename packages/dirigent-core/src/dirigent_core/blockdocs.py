"""Rendering the block catalog as the documentation page for it.

The rendered page is checked in, and a test regenerates it and fails when the file and the
catalog disagree.
"""

import json
from typing import Final, cast

from dirigent_client.schemas import BlockEntry, BlockKind, Catalog, SurfaceEntry
from dirigent_common import JsonMap
from dirigent_core.configdocs import first_paragraph, one_line

#: Relative to the repository root.
PAGE_PATH: Final = "docs/blocks.md"

BANNER: Final = "<!-- Generated from the installed block catalog by dirigent_core.blockdocs. Do not edit. -->"

PREAMBLE: Final = """# Block reference

Every block an instance has, with the config it takes and the output it produces. This page is
generated from the live catalog -- the same one `GET /blocks` serves, the same one the UI
builds forms from -- so it cannot drift from the code: a field added to a block either shows
up here or fails the build.

What a block is, and the contract behind these tables, is in
[the design document](design.md#2-the-five-plugin-surfaces). The short version:

- An **operator** does work. It either finishes and returns its output, or hands back a
  handle for the engine to probe, which is how a step waits for an hour without holding a
  worker for an hour.
- A **sensor** waits for the world. Each poke is one short, read-only observation, and "not
  yet" is the expected answer rather than a failure. `poll`, `deadline`, and `on_timeout` are
  step-level engine semantics, uniform across every sensor and never buried in a block's own
  config.

**Group** is the shelf a block declares for itself, and what every catalog is arranged by: the
four transform verbs are one `transform` group, and `shell.run`, `docker.run` and
`pipeline.run` are `execute`. A block that declares none takes the first half of its id.

Two properties are worth reading before a block is used:

- **Idempotent** says whether re-running the block after an unclear failure is safe. The
  engine spends the step's retry budget either way, so this is what to read before writing
  `max_attempts` above 1.
- **Local execution** says the block runs code on the worker. The engine refuses such a block
  unless the instance names it in `DIRIGENT_ENABLED_UNSAFE_BLOCKS`, because "can edit
  pipelines" must never quietly mean "can run code on workers".
"""

SURFACES_PREAMBLE: Final = """## Other surfaces

Blocks are two of the five surfaces a plugin contributes to. The other three are listed here
by id, since a document references them by code and never by id of any other kind.
"""

NO_DESCRIPTION: Final = "--"


def render(catalog: Catalog) -> str:
    """Render the whole catalog as the markdown page, deterministically."""
    parts = [BANNER, "", PREAMBLE]
    operators = [entry for entry in catalog.blocks if entry.kind is BlockKind.OPERATOR]
    sensors = [entry for entry in catalog.blocks if entry.kind is BlockKind.SENSOR]
    parts.append(_index(catalog.blocks))
    parts.append("## Operators\n")
    parts.extend(_block(entry) for entry in operators)
    parts.append("## Sensors\n")
    parts.extend(_block(entry) for entry in sensors)
    parts.append(SURFACES_PREAMBLE)
    parts.append(_surfaces("Storage schemes", "scheme", catalog.storage_schemes))
    parts.append(_surfaces("Notifiers", "id", catalog.notifiers))
    parts.append(_surfaces("Connection kinds", "id", catalog.connection_kinds))
    return "\n".join(parts).rstrip() + "\n"


def _index(blocks: list[BlockEntry]) -> str:
    """Render the table of every block."""
    rows = [
        f"| [`{entry.id}`](#{_anchor(entry.id)}) | {entry.kind.value} | {entry.group} "
        f"| {entry.summary} | `{entry.plugin}` |"
        for entry in blocks
    ]
    header = ["| Block | Kind | Group | Summary | Contributed by |", "| --- | --- | --- | --- | --- |"]
    return "\n".join([*header, *rows, ""])


def _block(entry: BlockEntry) -> str:
    """Render one block: what it is, how it behaves, and the two schemas it publishes."""
    lines = [f"### `{entry.id}`", "", entry.summary, "", _properties(entry), ""]
    lines.extend(["**Config**", "", _schema_table(entry.config_schema), ""])
    lines.extend(["**Output**", "", _schema_table(entry.output_schema), ""])
    return "\n".join(lines)


def _properties(entry: BlockEntry) -> str:
    """Render the retry-relevant and scheduling-relevant facts as one line each."""
    facts = [f"Contributed by `{entry.plugin}`."]
    facts.append("Idempotent." if entry.idempotent else "Not idempotent.")
    if entry.local_execution:
        facts.append("**Runs code on the worker**, so the instance must allowlist its id.")
    if entry.default_poll_seconds is not None:
        facts.append(f"Polls every {_duration(entry.default_poll_seconds)} unless the step says otherwise.")
    if entry.default_deadline_seconds is not None:
        facts.append(f"Gives up after {_duration(entry.default_deadline_seconds)} unless the step says otherwise.")
    return " ".join(facts)


def _duration(seconds: float) -> str:
    """Render a duration the way a document would write it."""
    for unit, size in (("h", 3600), ("m", 60)):
        if seconds >= size and seconds % size == 0:
            return f"{int(seconds // size)}{unit}"
    return f"{seconds:g}s"


def _schema_table(schema: JsonMap) -> str:
    """Render one JSON Schema object as a table of its fields."""
    properties = _mapping(schema.get("properties"))
    if not properties:
        return "_No fields._"
    required = {name for name in _sequence(schema.get("required")) if isinstance(name, str)}
    definitions = _mapping(schema.get("$defs"))
    rows: list[str] = []
    for name, raw in properties.items():
        field = _mapping(raw)
        rows.append(
            f"| `{name}` | `{_type_of(field, definitions)}` | {'yes' if name in required else ''} "
            f"| {_default_of(field, name in required)} | {_description_of(field)} |"
        )
    return "\n".join(["| Field | Type | Required | Default | Description |", "| --- | --- | --- | --- | --- |", *rows])


def _type_of(field: JsonMap, definitions: JsonMap) -> str:
    """Render a field's type readably, following the shapes pydantic actually emits.

    A union reads as "a or b" rather than "a | b": the result lands in a markdown table cell,
    where a pipe is a column separator whatever it is wrapped in.
    """
    resolved = _resolve(field, definitions)
    if "const" in resolved:
        return json.dumps(resolved["const"])
    enum = _sequence(resolved.get("enum"))
    if enum:
        return " or ".join(json.dumps(value) for value in enum)
    for keyword in ("anyOf", "oneOf", "allOf"):
        branches = _sequence(resolved.get(keyword))
        if branches:
            alternatives = [_type_of(_mapping(branch), definitions) for branch in branches]
            return " or ".join(dict.fromkeys(alternatives))
    declared = resolved.get("type")
    if declared == "array":
        return f"{_type_of(_mapping(resolved.get('items')), definitions)}[]"
    if declared == "object":
        values = _mapping(resolved.get("additionalProperties"))
        if not values:
            return "object"
        of = _type_of(values, definitions)
        return "object" if of == "any" else f"object of {of}"
    if isinstance(declared, str):
        formatted = resolved.get("format")
        return f"{declared} ({formatted})" if isinstance(formatted, str) else declared
    return "any"


def _resolve(field: JsonMap, definitions: JsonMap) -> JsonMap:
    """Follow a ``$ref`` into the schema's own ``$defs``, which is the only ref pydantic emits."""
    reference = field.get("$ref")
    if not isinstance(reference, str):
        return field
    name = reference.rsplit("/", 1)[-1]
    return _mapping(definitions.get(name)) or field


def _default_of(field: JsonMap, required: bool) -> str:
    """Render a field's default, distinguishing "none" from "there is no default"."""
    if required or "default" not in field:
        return ""
    return f"`{json.dumps(field['default'])}`"


def _description_of(field: JsonMap) -> str:
    """Render what a field is on one line, since a table cell is one line.

    The first paragraph only, for the reason ``described`` gives: a config field inherited by
    three blocks renders three times, and a paragraph of rationale renders three times with it.
    """
    text = field.get("description")
    if not isinstance(text, str) or not text.strip():
        return NO_DESCRIPTION
    return one_line(first_paragraph(text)).replace("|", "\\|")


def _surfaces(title: str, label: str, entries: list[SurfaceEntry]) -> str:
    """Render one non-block surface's entries as a short table."""
    if not entries:
        return f"### {title}\n\n_None installed._\n"
    rows = [f"| `{entry.id}` | `{entry.plugin}` |" for entry in entries]
    return "\n".join(
        [
            f"### {title}",
            "",
            f"| {title[:-1] if label == 'id' else label.title()} | Contributed by |",
            "| --- | --- |",
            *rows,
            "",
        ]
    )


def _anchor(block_id: str) -> str:
    """Render the anchor mkdocs gives a heading whose text is a backticked block id."""
    return block_id.replace(".", "")


def _mapping(value: object) -> JsonMap:
    """Read a schema node that should be an object, or nothing."""
    return cast("JsonMap", value) if isinstance(value, dict) else {}


def _sequence(value: object) -> list[object]:
    """Read a schema node that should be a list, or nothing."""
    return cast("list[object]", value) if isinstance(value, list) else []
