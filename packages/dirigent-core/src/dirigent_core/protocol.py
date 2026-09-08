"""One event protocol: NDJSON on the wire and a fixed console rendering.

A record is a flat ordered mapping whose leading keys are reserved and whose remaining keys
are whatever the event carries. :func:`parse` turns one JSON line back into a record, so a
console rendering can be reconstructed from a stored stream rather than only from the process
that produced it.
"""

import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import datetime
from typing import Any, Final, Literal, cast

#: The version every structured record carries. Within a version a field may be added, never
#: removed and never retyped; a shape that cannot be reached that way takes the next number.
#: Adding a record kind is compatible within a version; removing or repurposing one is not.
PROTOCOL_VERSION: Final = 1

VERSION_KEY: Final = "v"

#: Keys the protocol owns and every record carries. A field named one of these is namespaced
#: rather than allowed to shadow the key a parser reads the record by. Everything else --
#: ``run_id``, ``block``, ``attempt`` -- is convention between emitters, not reserved.
RESERVED: Final[tuple[str, ...]] = (VERSION_KEY, "at", "level", "kind", "step", "item", "message")

#: The keys the console line spends its leading columns on, in that order.
POSITIONAL: Final[tuple[str, ...]] = ("at", "level", "kind", "step", "item", "message")

#: What a console line prints where a positional column has no value.
ABSENT: Final = "-"

LEVEL_WIDTH: Final = 8
MESSAGE_WIDTH: Final = 30

#: Nested values are spread into ``prefix.key`` fields for the flat spellings.
NESTED_PREFIXES: Final[Mapping[str, str]] = {"output": "output.", "fields": ""}

#: What a block's field is renamed to when it is called one of the reserved names.
NAMESPACE: Final = "fields."

type Record = dict[str, Any]
type Format = Literal["console", "json"]

#: The outputs, in the order they are offered to somebody who spelled one wrong.
FORMATS: Final[tuple[str, ...]] = ("console", "json")
type Paint = Callable[[str, str], str]

#: A bare value: printable, and free of the characters that end a field.
_BARE = re.compile(r"^[!-~]+$")


def make(
    kind: str,
    /,
    *,
    at: datetime | str | None = None,
    level: str = "info",
    step: str | None = None,
    item: str | None = None,
    message: str = "",
    **data: Any,
) -> Record:
    """Build one record: the reserved keys in canonical order, then the event's own fields.

    A field whose name is reserved is namespaced, so an event can never shadow the key a
    parser reads its level or its correlation from.
    """
    record: Record = {
        VERSION_KEY: PROTOCOL_VERSION,
        "at": _instant(at),
        "level": level,
        "kind": kind,
        "step": step,
        "item": item,
        "message": message,
    }
    for name, value in data.items():
        record[_safe_name(name, record)] = value
    return record


def _safe_name(name: str, record: Record) -> str:
    """Name a field so it cannot displace a key the protocol already owns."""
    return f"{NAMESPACE}{name}" if name in record else name


def _instant(at: datetime | str | None) -> str | None:
    """Render a moment as the ISO-8601 instant every spelling carries."""
    if at is None or isinstance(at, str):
        return at
    return at.isoformat(timespec="milliseconds")


def flatten(record: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """Spread a record's trailing fields into the flat ``key=value`` pairs a line carries.

    A nested mapping is spread rather than printed as one blob: ``output`` under its own
    prefix, a block's own fields under their own names, and a name that collides with a
    reserved key namespaced.
    """
    pairs: list[tuple[str, Any]] = []
    for name, value in record.items():
        if name in POSITIONAL or name == VERSION_KEY:
            continue
        if name == "logger" and record.get("step") is None:
            # The source column already says it; a line does not say one thing twice.
            continue
        prefix = NESTED_PREFIXES.get(name)
        if prefix is not None and isinstance(value, Mapping):
            nested = cast("Mapping[str, Any]", value)
            pairs.extend(
                (f"{prefix}{key}" if f"{prefix}{key}" not in RESERVED else f"{NAMESPACE}{key}", item)
                for key, item in nested.items()
            )
            continue
        pairs.append((name, value))
    return [(name, value) for name, value in pairs if value is not None]


def _plain(role: str, text: str) -> str:
    """Paint nothing: the identity used when a line is going somewhere without colour."""
    del role
    return text


def console(record: Mapping[str, Any], *, paint: Paint = _plain, local: bool = True, pad: bool = True) -> str:
    """Render one record as the fixed-grammar console line.

    Columns are padded, never cut: a value wider than its column pushes the line out rather
    than losing the half that says which one it is. ``pad=False`` spends no columns at all
    and is otherwise the same grammar.
    """
    at = record.get("at")
    stamp = _stamp(at, local=local) if isinstance(at, str) else ABSENT
    level = str(record.get("level") or "info")
    message = str(record.get("message") or "")
    parts = [
        paint("time", stamp),
        paint(f"level.{level}", f"[{_pad(level, LEVEL_WIDTH) if pad else level}]"),
        paint("message", _pad(message, MESSAGE_WIDTH) if pad else message),
        paint(f"step.{record.get('step') or ''}", f"[{origin(record)}]"),
    ]
    parts.extend(paint("key", f"{name}=") + paint("value", field_value(value)) for name, value in flatten(record))
    return " ".join(parts)


def origin(record: Mapping[str, Any]) -> str:
    """Render what the line came from: the kind, and the step and element when it has one."""
    kind = str(record.get("kind") or "log")
    source = _source(record)
    return kind if source == ABSENT else f"{kind} {source}"


def _source(record: Mapping[str, Any]) -> str:
    """Render the source column: what wrote the line.

    A run's own event says which step, and which fan-out element that step is working on. A
    logging event has no step and says which logger, which is the same question answered by
    the part of the program that has an answer.
    """
    step = record.get("step")
    if step is None:
        logger = record.get("logger")
        return str(logger) if logger else ABSENT
    item = record.get("item")
    return f"{step}[{item}]" if item is not None else str(step)


def _pad(text: str, width: int) -> str:
    """Pad a column to its width, and leave a wider value alone."""
    return f"{text:<{width}}"


def _stamp(at: str, *, local: bool) -> str:
    """Render an instant for a person: the same moment, in the reader's own offset."""
    if not local:
        return at
    try:
        parsed = datetime.fromisoformat(at)
    except ValueError:
        return at
    return parsed.astimezone().isoformat(timespec="milliseconds")


def field_value(value: object) -> str:
    """Render one field value for the console line, whole.

    A structure is printed as compact JSON without quotes around it, because a line that
    escaped every quote inside a body would be unreadable and no easier to parse: a value
    starting with ``{`` or ``[`` is read as one JSON value.
    """
    if isinstance(value, str):
        return value if _BARE.match(value) else quoted(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    return json.dumps(value, default=str, separators=(",", ":"))


def quoted(text: str) -> str:
    """Render a string as one JSON string, which is where a reader knows it ends."""
    return json.dumps(text, ensure_ascii=False)


def as_json(record: Mapping[str, Any]) -> str:
    """Encode one record as one compact JSON line, with structures left nested."""
    return json.dumps(dict(record), default=str, separators=(",", ":"))


def parse(line: str) -> Record | None:
    """Read one JSON line back into a record, or report that it is not one of ours.

    A line that does not parse is somebody else's, and the caller passes it through rather
    than failing: a real log interleaves.
    """
    text = line.strip()
    if not text:
        return None
    return _from_json(text)


def _from_json(text: str) -> Record | None:
    """Read one JSON line, adapting a structlog record into the protocol's own shape."""
    try:
        loaded = json.loads(text)
    except ValueError:
        return None
    if not isinstance(loaded, dict):
        return None
    return adopt(cast("dict[str, Any]", loaded))


def adopt(body: dict[str, Any]) -> Record | None:
    """Read a structlog event as a record, or report that it is not one.

    A logging event says ``event`` and ``timestamp`` where a record says ``message`` and
    ``at``, and carries the rest of itself as fields already. Renaming the two is the whole
    of the adaptation, which is what lets one grammar render a run's story and the logging
    beside it.
    """
    if "message" not in body and "event" in body:
        body["message"] = body.pop("event")
    if "at" not in body and "timestamp" in body:
        body["at"] = body.pop("timestamp")
    if "message" not in body:
        return None
    return _canonical(body)


def _canonical(body: Mapping[str, Any]) -> Record:
    """Put a parsed body back into canonical key order, whatever order it arrived in."""
    record: Record = {VERSION_KEY: body.get(VERSION_KEY, PROTOCOL_VERSION)}
    for name in POSITIONAL:
        record[name] = body.get(name)
    record["level"] = record["level"] or "info"
    record["kind"] = record["kind"] or "log"
    record["message"] = record["message"] or ""
    for name, value in body.items():
        if name not in record:
            record[name] = value
    return record


def render(record: Mapping[str, Any], output: Format, *, paint: Paint = _plain) -> str:
    """Encode one record for a machine, or render it for a person."""
    if output == "json":
        return as_json(record)
    return console(record, paint=paint)


def each(lines: Sequence[str] | Iterator[str]) -> Iterator[tuple[str, Record | None]]:
    """Walk a stream, pairing each line with the record it holds, or None when it holds none."""
    for line in lines:
        yield line.rstrip("\n"), parse(line)
