"""Building a run's parameters from the command line, against the pipeline's own schema.

Precedence is schema defaults, then ``-P`` files in the order given, then ``-p`` flags in
the order given. Objects deep-merge; arrays and scalars replace, except that a bracketed
index in a ``-p`` key sets one element of an array in place.
"""

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final, cast

import yaml

from dirigent_common import JsonMap
from dirigent_core.documents import safe_load

TRUE_WORDS: Final = frozenset({"true", "yes", "y", "on", "1"})
FALSE_WORDS: Final = frozenset({"false", "no", "n", "off", "0"})

STRUCTURED: Final = frozenset({"object", "array"})

#: What ``[]`` addresses: one past the last element, wherever the array happens to end.
APPEND: Final = -1

#: One dotted segment: a name, then any number of ``[index]`` or ``[]`` brackets.
SEGMENT: Final = re.compile(r"(?P<name>[^\[\]]*)(?P<indices>(?:\[[^\[\]]*\])*)")

INDEX: Final = re.compile(r"\[([^\[\]]*)\]")

#: A step of a parsed key: an object key, an array index, or ``APPEND``.
type Step = str | int


class ParamError(Exception):
    """A parameter could not be read, addressed, or coerced; the message says which."""


def parse_pair(pair: str) -> tuple[str, str]:
    """Split one ``key=value`` argument, refusing anything that is not one."""
    if "=" not in pair:
        raise ParamError(f"-p expects key=value, not {pair!r}")
    key, _, value = pair.partition("=")
    if not key:
        raise ParamError(f"-p expects key=value, not {pair!r}")
    return key, value


def split_key(key: str) -> list[Step]:
    """Split a key into its path of object keys and array indices."""
    if not key:
        raise ParamError(f"-p {key}: a dotted key names each level, so it may not have an empty segment")
    path: list[Step] = []
    for segment in key.split("."):
        match = SEGMENT.fullmatch(segment)
        if match is None:
            raise ParamError(f"-p {key}: {segment!r} is not a name followed by [index] brackets")
        name = match["name"]
        if not name:
            raise ParamError(f"-p {key}: a dotted key names each level, so it may not have an empty segment")
        if name.isdigit():
            raise ParamError(
                f"-p {key}: a dotted path cannot tell the index {name!r} from an object key named {name!r}. "
                f"Address an element with brackets instead ({path[-1] if path else 'name'}[{name}]=...)"
            )
        path.append(name)
        path.extend(_index(raw, key) for raw in INDEX.findall(match["indices"]))
    return path


def _index(raw: str, key: str) -> int:
    """Read what one pair of brackets addresses: an element, or the end of the array."""
    if not raw:
        return APPEND
    if not raw.isdigit():
        if raw.lstrip("-").isdigit():
            raise ParamError(f"-p {key}: an index counts from the start of the array, so {raw!r} is not one")
        raise ParamError(f"-p {key}: an index is a whole number or nothing at all, not {raw!r}")
    return int(raw)


def render_path(path: Sequence[Step]) -> str:
    """Render a parsed path the way it is written on the command line."""
    written = ""
    for step in path:
        if isinstance(step, str):
            written = f"{written}.{step}" if written else step
        else:
            written += "[]" if step == APPEND else f"[{step}]"
    return written


def _article(word: str) -> str:
    """Prefix a schema's word with the article that reads."""
    return f"an {word}" if word[:1] in "aeiou" else f"a {word}"


def _holds(value: Any) -> str:
    """Name what a value already at a path is, for a message about addressing it wrongly."""
    match value:
        case bool():
            return "a boolean"
        case dict():
            return "an object"
        case list():
            return "an array"
        case int() | float():
            return "a number"
        case str():
            return "a string"
        case _:
            return "a scalar"


def read_params_file(path: Path) -> JsonMap:
    """Read a whole parameter payload from a YAML or JSON file."""
    try:
        loaded = safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise ParamError(f"{path} could not be read: {error}") from error
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ParamError(f"{path} should hold a mapping of parameters, not {type(loaded).__name__}")
    return cast("JsonMap", loaded)


def _schema_at(schema: JsonMap, path: Sequence[Step], where: str) -> JsonMap | None:
    """Resolve the subschema a path addresses, or say the path is not declared.

    ``where`` names the channel a value arrived on -- a flag or a file -- so both are refused
    by this one walk rather than by two rules that can drift apart.
    """
    current: JsonMap | None = schema
    walked: list[Step] = []
    for step in path:
        if current is None:
            return None
        declared = _type_of(current)
        if isinstance(step, int):
            if declared is not None and declared != "array":
                raise ParamError(
                    f"{where}: the schema calls {render_path(walked)!r} {_article(declared)}, "
                    f"so it takes a key, not an index"
                )
            items: object = current.get("items")
            current = cast("JsonMap", items) if isinstance(items, dict) else None
            walked.append(step)
            continue
        if declared == "array":
            raise ParamError(
                f"{where}: the schema calls {render_path(walked)!r} an array, "
                f"so it takes an index, not the key {step!r}"
            )
        raw: object = current.get("properties")
        properties = cast("JsonMap", raw) if isinstance(raw, dict) else None
        found = properties.get(step) if properties is not None else None
        if found is None:
            if _is_open(current, properties):
                return None
            location = render_path([*walked, step])
            known = _known(current)
            raise ParamError(f"{where}: the pipeline declares no parameter {location!r} ({known})")
        current = cast("JsonMap", found)
        walked.append(step)
    return current


def _is_open(schema: JsonMap, properties: JsonMap | None) -> bool:
    """Report whether a schema level accepts a name it does not list.

    Stricter than JSON Schema, which allows extra properties unless told otherwise: a
    level that lists any property is treated as closed unless it also says
    ``additionalProperties``.
    """
    if not properties:
        return True
    extra = schema.get("additionalProperties")
    return extra is True or isinstance(extra, dict)


def _known(schema: JsonMap) -> str:
    """Render what a schema level does declare, for an error naming an unknown path."""
    properties: object = schema.get("properties")
    if not isinstance(properties, dict):
        return "it declares no parameters"
    names = ", ".join(sorted(cast("Mapping[str, object]", properties)))
    return f"it declares {names}" if names else "it declares no parameters"


def coerce(value: str, schema: JsonMap | None, key: str) -> Any:
    """Turn one command-line string into the value the schema says belongs at that path."""
    declared = _type_of(schema)
    if declared in STRUCTURED:
        return _structured(value, declared, key)
    match declared:
        case "integer":
            return _integer(value, key)
        case "number":
            return _number(value, key)
        case "boolean":
            return _boolean(value, key)
        case "string":
            return _checked_enum(value, schema, key)
        case _:
            parsed: Any = safe_load(value) if value else value
            return _checked_enum(parsed, schema, key)


def _type_of(schema: JsonMap | None) -> str | None:
    """Read the type a subschema declares, tolerating the list form, ``anyOf`` and enum-only.

    An optional field is spelled ``anyOf: [{type: string}, {type: null}]`` by the generator
    every connection kind's schema comes from, and a branch left unread there falls through to
    YAML, where ``#ops`` is a comment rather than a channel.
    """
    if schema is None:
        return None
    declared = schema.get("type")
    if isinstance(declared, str):
        return declared
    if isinstance(declared, list):
        strings = [item for item in cast("list[object]", declared) if isinstance(item, str) and item != "null"]
        return strings[0] if strings else None
    if isinstance(schema.get("anyOf"), list):
        for branch in cast("list[object]", schema["anyOf"]):
            if not isinstance(branch, dict):
                continue
            found = _type_of(cast("JsonMap", branch))
            if found is not None and found != "null":
                return found
    if isinstance(schema.get("enum"), list):
        members = cast("list[object]", schema["enum"])
        return "string" if all(isinstance(item, str) for item in members) else None
    return None


def _structured(value: str, declared: str, key: str) -> Any:
    """Read an inline object or array, in either JSON or YAML."""
    try:
        parsed = safe_load(value)
    except yaml.YAMLError as error:
        raise ParamError(f"-p {key}: {value!r} is not valid JSON or YAML ({error})") from error
    if declared == "array" and not isinstance(parsed, list):
        raise ParamError(f"-p {key}: this parameter is an array, and {value!r} is not one")
    if declared == "object" and not isinstance(parsed, dict):
        raise ParamError(f"-p {key}: this parameter is an object, and {value!r} is not one")
    return cast("Any", parsed)


def _integer(value: str, key: str) -> int:
    """Read an integer, refusing anything that only looks like one."""
    try:
        return int(value)
    except ValueError as error:
        raise ParamError(f"-p {key}: this parameter is an integer, and {value!r} is not one") from error


def _number(value: str, key: str) -> float:
    """Read a number."""
    try:
        return float(value)
    except ValueError as error:
        raise ParamError(f"-p {key}: this parameter is a number, and {value!r} is not one") from error


def _boolean(value: str, key: str) -> bool:
    """Read a boolean from the words a person actually types."""
    lowered = value.strip().lower()
    if lowered in TRUE_WORDS:
        return True
    if lowered in FALSE_WORDS:
        return False
    raise ParamError(f"-p {key}: this parameter is a boolean; write true or false, not {value!r}")


def _checked_enum(value: Any, schema: JsonMap | None, key: str) -> Any:
    """Refuse a value the schema's enum does not list, naming what it does list."""
    if schema is None:
        return value
    members = schema.get("enum")
    if isinstance(members, list) and value not in members:
        allowed = ", ".join(repr(item) for item in cast("list[object]", members))
        raise ParamError(f"-p {key}: {value!r} is not one of {allowed}")
    return value


def assign(target: JsonMap, path: Sequence[Step], value: Any, key: str) -> None:
    """Set a value at a parsed path, creating the objects and arrays it passes through."""
    container: Any = target
    for position, step in enumerate(path[:-1]):
        container = _descend(
            container, step, path[: position + 1], wants_list=isinstance(path[position + 1], int), key=key
        )
    _read(container, path[-1], path, key)
    _put(container, path[-1], value)


def _descend(container: Any, step: Step, walked: Sequence[Step], *, wants_list: bool, key: str) -> Any:
    """Read one step further in, creating the container there when nothing is yet."""
    existing = _read(container, step, walked, key)
    if existing is None:
        fresh: Any = [] if wants_list else {}
        _put(container, step, fresh)
        return fresh
    if not _fits(existing, wants_list=wants_list):
        wanted = "an array" if wants_list else "an object"
        raise ParamError(f"-p {key}: {render_path(walked)!r} holds {_holds(existing)}, not {wanted}")
    return existing


def _fits(value: Any, *, wants_list: bool) -> bool:
    """Report whether a value already at a path is the container the next step needs."""
    return isinstance(value, dict | list) and isinstance(value, list) == wants_list


def _read(container: Any, step: Step, walked: Sequence[Step], key: str) -> Any:
    """Read what is at one step, refusing a step the container cannot take."""
    parent = render_path(walked[:-1])
    if isinstance(step, str):
        if isinstance(container, list):
            raise ParamError(f"-p {key}: {parent!r} holds an array, so {step!r} is not a key it takes")
        keys: JsonMap = container
        return keys.get(step)
    if isinstance(container, dict):
        raise ParamError(f"-p {key}: {parent!r} holds an object, so [{step}] is not an element it takes")
    elements: list[Any] = container
    if step == APPEND or step == len(elements):
        return None
    if step > len(elements):
        raise ParamError(
            f"-p {key}: {parent!r} holds {_count(len(elements))}, so [{step}] would leave a gap; "
            f"the next element is [{len(elements)}], which [] also writes"
        )
    return elements[step]


def _count(total: int) -> str:
    """Say how many elements an array holds."""
    return "1 element" if total == 1 else f"{total} elements"


def _put(container: Any, step: Step, value: Any) -> None:
    """Write a value at one step, appending when the index is the end of the array."""
    if isinstance(step, str):
        cast("JsonMap", container)[step] = value
        return
    elements = cast("list[Any]", container)
    if step == APPEND or step == len(elements):
        elements.append(value)
    else:
        elements[step] = value


def deep_merge(base: JsonMap, incoming: Mapping[str, Any]) -> JsonMap:
    """Merge one mapping into another: objects merge, everything else replaces."""
    merged = dict(base)
    for key, value in incoming.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = deep_merge(cast("JsonMap", existing), cast("Mapping[str, Any]", value))
        else:
            merged[key] = value
    return merged


def build_params(
    schema: JsonMap,
    *,
    pairs: Sequence[str] = (),
    files: Sequence[Path] = (),
) -> JsonMap:
    """Build one parameter object from files and flags, coerced against the pipeline's schema.

    A name the schema does not declare is refused whichever channel it arrived on, so a typo
    in a file fails here rather than being stored and ignored.
    """
    params: JsonMap = {}
    for path in files:
        payload = read_params_file(path)
        for name in payload:
            _schema_at(schema, [name], f"params file {path}")
        params = deep_merge(params, payload)
    for pair in pairs:
        key, raw = parse_pair(pair)
        parts = split_key(key)
        subschema = _schema_at(schema, parts, f"-p {key}")
        assign(params, parts, coerce(raw, subschema, key), key)
    return params
