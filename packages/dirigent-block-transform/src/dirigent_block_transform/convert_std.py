"""The ``std`` engine for the convert verb: json, ndjson, csv, yaml and xml, on the standard library."""

import csv
import datetime
import io
import json
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Mapping, Sequence
from typing import Any, Final, cast

import yaml
from pydantic import JsonValue

from dirigent_plugin import Converter, TransformError

#: The three spellings of a sequence of records, which convert between each other freely.
SEQUENCE_FORMATS: Final = ("json", "ndjson", "csv")

#: Every pair this engine re-encodes, source first. The frame refuses everything else.
PAIRS: Final = frozenset(
    {(source, target) for source in SEQUENCE_FORMATS for target in SEQUENCE_FORMATS if source != target}
    | {("json", "yaml"), ("yaml", "json"), ("ndjson", "yaml"), ("yaml", "ndjson")}
    | {("json", "xml"), ("xml", "json"), ("xml", "ndjson")}
)

#: What a target format calls one element of the sequence it writes.
UNIT: Final = {"json": "element", "ndjson": "line", "csv": "row", "yaml": "document"}

#: The key an element's attribute takes, prefixed so it can never collide with a child's tag.
ATTRIBUTE_PREFIX: Final = "@"

#: The key an element's text takes where the element also has attributes.
TEXT_KEY: Final = "#text"

#: An XML name, in ElementTree's spelling: a local name, optionally behind a ``{uri}``.
XML_NAME: Final = re.compile(r"(\{[^{}]+\})?[A-Za-z_][\w.\-]*\Z")


def _named(value: JsonValue) -> str:
    """Say what a JSON value is, so a refusal names what arrived and not only what was wanted."""
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "an array"
    if isinstance(value, str):
        return "a string"
    # Before the number check, because a bool is an int in Python and is not one in JSON.
    if isinstance(value, bool):
        return "a boolean"
    if value is None:
        return "null"
    return "a number"


class StdConverter(Converter):
    """Re-encodes records and values between json, ndjson, csv, yaml and xml.

    json, ndjson and csv say the same thing: a sequence of records. json says it as one
    array, ndjson as one JSON value per line, and csv as a header and its rows. So a
    conversion between those three is reading the sequence out of one spelling and writing
    it in another, and everything the engine refuses there is a source that is not that
    sequence.

    csv is the format that carries less than the other two. A cell is text, so everything
    read out of a csv is a string, and a record with a nested value has no csv spelling at
    all. Both are refusals rather than conversions, because a codec that guesses a number
    out of text, or flattens an object into a cell, has not preserved the content.

    yaml is read and written two ways, because YAML spells two things. A YAML document is
    one value, so yaml and json trade one whole value either way and a config file becomes
    the object it describes. A YAML stream is many documents, so yaml and ndjson trade one
    document per line. A YAML value JSON has no word for -- a date, a set, binary, a tagged
    node, a mapping key that is not a string, a number that is nan or infinite -- is refused
    naming its path, because writing it as text would be a guess about what it meant.

    xml carries one root element, and the mapping is the one that round-trips: an element is
    an object, an attribute is a key prefixed with ``@``, the text is ``#text`` where the
    element has attributes and the bare string where it has none, a child element is a key of
    its tag, and a tag that repeats is a list in document order. The prefix is what makes it
    reversible: ``@`` cannot start an XML name, so an attribute and a child of the same name
    never collide and every key says which it came from. An empty element is null, everything
    read out of an element is text the way everything read out of a csv is, and mixed content
    -- text beside child elements -- is refused naming the element, because the mapping has
    nowhere to put it. json to xml therefore wants an object of exactly one key, which names
    the root element.

    xml to ndjson is the streaming direction: the root's children are the records, one line
    each, read with ``iterparse`` and dropped as they are written, so a document far larger
    than the records it holds converts. It has no reverse, because a line carries no root
    element name to write one under; convert to json and name the root there.

    No document type declaration is read. A DTD is where entities and external files enter an
    XML document, so one is refused rather than parsed.
    """

    kind = "std"
    summary = "Convert between json, ndjson, csv, yaml and xml."
    pairs = PAIRS

    def convert(self, source: bytes, *, source_format: str, target_format: str) -> bytes:
        """Re-encode the payload, by whole value where yaml and json meet and by sequence otherwise."""
        text = _decode(source)
        if (source_format, target_format) == ("yaml", "json"):
            return _dump_json(_read_yaml_document(text))
        if (source_format, target_format) == ("json", "yaml"):
            return _dump_yaml(_read_json_value(text))
        if source_format == "xml":
            return _read_xml(text, target_format)
        if target_format == "xml":
            return _write_xml(_read_json_value(text))
        records = _read(text, source_format, target_format)
        return _write(records, target_format).encode()


def _decode(source: bytes) -> str:
    """Read the payload as UTF-8, refusing bytes that are not, at the byte that is not."""
    try:
        return source.decode("utf-8")
    except UnicodeDecodeError as error:
        raise TransformError(
            f"the input is not UTF-8 text: {error.reason} at byte {error.start}; convert.std reads and writes UTF-8"
        ) from error


def _dump_json(value: JsonValue) -> bytes:
    """Write one JSON value, compactly, as the bytes the frame hands on."""
    return json.dumps(value, separators=(",", ":")).encode()


def _read(text: str, source_format: str, target_format: str) -> list[JsonValue]:
    """Read the sequence of records the source format spells out."""
    if source_format == "json":
        return _read_json(text, target_format)
    if source_format == "ndjson":
        return _read_ndjson(text)
    if source_format == "yaml":
        return _read_yaml_stream(text)
    return _read_csv(text)


def _read_json_value(text: str) -> JsonValue:
    """Read one JSON value of any shape, for the targets that carry a value rather than a sequence."""
    try:
        parsed: JsonValue = json.loads(text)
    except ValueError as error:
        raise TransformError(f"the input is not JSON: {error}") from error
    return parsed


def _read_json(text: str, target_format: str) -> list[JsonValue]:
    """Read one JSON array, refusing any other JSON value: a sequence is what is being converted."""
    parsed = _read_json_value(text)
    if not isinstance(parsed, list):
        raise TransformError(
            f"json to {target_format} writes one {UNIT[target_format]} per element, so the input has to be "
            f"a JSON array, and this one is {_named(parsed)}"
        )
    return parsed


def _read_ndjson(text: str) -> list[JsonValue]:
    """Read one JSON value per line, skipping blank lines and naming the line that is not JSON."""
    records: list[JsonValue] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except ValueError as error:
            raise TransformError(f"line {number} of the input is not JSON: {error}") from error
    return records


def _read_csv(text: str) -> list[JsonValue]:
    """Read the header row and its rows, as objects whose every value is a string."""
    rows = csv.reader(io.StringIO(text, newline=""))
    header = next(rows, None)
    if header is None:
        return []
    _check_header(header)
    records: list[JsonValue] = []
    for number, row in enumerate(rows, start=1):
        if not row:
            continue
        if len(row) > len(header):
            raise TransformError(
                f"row {number} of the csv has more cells than the header names columns, "
                f"and a cell no column names has nowhere to go"
            )
        records.append({name: row[index] if index < len(row) else "" for index, name in enumerate(header)})
    return records


def _columns_phrase(positions: list[int]) -> str:
    """Word one or more column positions, counting from one."""
    listed = ", ".join(str(position) for position in positions)
    return f"column {listed}" if len(positions) == 1 else f"columns {listed}"


def _check_header(header: list[str]) -> None:
    """Refuse a header that leaves a name empty or repeats one.

    A record key names its column, so neither has a record spelling: keeping one of two
    columns that share a name, or keying a column by the empty string, drops content while
    reporting success.
    """
    positions: dict[str, list[int]] = {}
    for index, name in enumerate(header, start=1):
        positions.setdefault(name, []).append(index)
    unnamed = positions.pop("", None)
    if unnamed is not None:
        raise TransformError(
            f"the csv header has no name at {_columns_phrase(unnamed)}, and a record key names "
            f"its column; name it before converting"
        )
    repeated = [(name, where) for name, where in positions.items() if len(where) > 1]
    if repeated:
        listed = "; ".join(f"{name!r} at {_columns_phrase(where)}" for name, where in repeated)
        raise TransformError(
            f"the csv header repeats a column name: {listed}; a record key names one column, "
            f"so rename them before converting"
        )


def _write(records: list[JsonValue], target_format: str) -> str:
    """Write the sequence of records in the target format."""
    if target_format == "json":
        return json.dumps(records, separators=(",", ":"))
    if target_format == "ndjson":
        return "".join(f"{json.dumps(record, separators=(',', ':'))}\n" for record in records)
    if target_format == "yaml":
        return _dump_yaml_stream(records)
    return _write_csv(records)


def _write_csv(records: list[JsonValue]) -> str:
    """Write a header of every key any row has, in first-seen order, and one row per record."""
    rows: list[dict[str, JsonValue]] = []
    header: list[str] = []
    for number, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise TransformError(f"row {number} of the input is {_named(record)}, and a csv row is a flat object")
        rows.append(record)
        header.extend(key for key in record if key not in header)
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    for number, row in enumerate(rows, start=1):
        writer.writerow([_cell(row.get(key), number, key) for key in header])
    return out.getvalue()


def _cell(value: JsonValue, number: int, key: str) -> str:
    """Render one value as csv text, refusing the nested ones csv has no spelling for."""
    if isinstance(value, dict | list):
        raise TransformError(
            f"row {number} has a nested value at {key!r}, and a csv cell holds one value; "
            f"flatten it before converting, because writing it as text would not be the same content"
        )
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)


class _Tagged:
    """A node carrying a YAML tag the safe loader has no type for, kept so a refusal can name its path."""

    def __init__(self, tag: str) -> None:
        self.tag = tag


class _JsonSafeLoader(yaml.SafeLoader):
    """The safe loader, with an unknown tag built into a marker rather than refused without a path."""


def _construct_tagged(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> _Tagged:
    """Build the marker for any tag the safe loader has no constructor of its own for."""
    return _Tagged(node.tag)


yaml.add_multi_constructor("", _construct_tagged, Loader=_JsonSafeLoader)


def _load_yaml(text: str) -> list[Any]:
    """Read every document of a YAML stream with the safe loader, naming where it stops."""
    try:
        return list(yaml.load_all(text, Loader=_JsonSafeLoader))
    except yaml.YAMLError as error:
        raise TransformError(f"the input is not YAML: {' '.join(str(error).split())}") from error


def _read_yaml_document(text: str) -> JsonValue:
    """Read one YAML document as one value, refusing a stream that holds more than one."""
    documents = _load_yaml(text)
    if len(documents) > 1:
        raise TransformError(
            f"the input is a YAML stream of {len(documents)} documents, and yaml to json reads one document "
            f"as one value; convert it to ndjson to write one line per document"
        )
    return _as_json(documents[0], "$") if documents else None


def _read_yaml_stream(text: str) -> list[JsonValue]:
    """Read a YAML stream as its sequence of records, one per document."""
    return [_as_json(document, f"$[{index}]") for index, document in enumerate(_load_yaml(text))]


def _step(path: str, key: str) -> str:
    """Extend a path by one mapping key, bracketing the keys that are not plain names."""
    return f"{path}.{key}" if re.fullmatch(r"[A-Za-z_]\w*", key) else f"{path}[{key!r}]"


def _unspellable(value: Any) -> str:
    """Say what a YAML value is that JSON has no word for, and what to do about it."""
    if isinstance(value, _Tagged):
        return f"tagged {value.tag!r}, and JSON has no tags; drop the tag to convert what it holds"
    if isinstance(value, datetime.datetime):
        return "a timestamp, and JSON has no timestamp; quote it in the source to convert it as text"
    if isinstance(value, datetime.date):
        return "a date, and JSON has no date; quote it in the source to convert it as text"
    if isinstance(value, set | frozenset):
        return "a set, and JSON has no set; write it as a sequence to convert it"
    if isinstance(value, bytes | bytearray):
        return "binary, and JSON has no binary; quote it in the source to convert it as text"
    return f"{type(value).__name__}, which JSON has no word for"


def _as_json(value: Any, path: str) -> JsonValue:
    """Read a value the YAML loader built as JSON, refusing the first part of it JSON cannot spell."""
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise TransformError(
                f"the YAML number at {path} is {value}, and JSON writes no nan or infinity; "
                f"quote it in the source to convert it as text"
            )
        return value
    if isinstance(value, list):
        items = cast("Sequence[Any]", value)
        return [_as_json(item, f"{path}[{index}]") for index, item in enumerate(items)]
    if isinstance(value, dict):
        record: dict[str, JsonValue] = {}
        for key, item in cast("Mapping[Any, Any]", value).items():
            if not isinstance(key, str):
                raise TransformError(
                    f"the YAML mapping at {path} is keyed by {key!r}, and a JSON key is a string; "
                    f"quote the key in the source to convert it"
                )
            record[key] = _as_json(item, _step(path, key))
        return record
    raise TransformError(f"the YAML value at {path} is {_unspellable(value)}")


def _dump_yaml(value: JsonValue) -> bytes:
    """Write one JSON value as one YAML document, in block style and in the order it arrived."""
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True, default_flow_style=False).encode()


def _dump_yaml_stream(records: list[JsonValue]) -> str:
    """Write a sequence of records as a YAML stream, each record its own document."""
    return yaml.safe_dump_all(
        records, sort_keys=False, allow_unicode=True, default_flow_style=False, explicit_start=True
    )


def _refuse_doctype(text: str) -> None:
    """Refuse a document type declaration, walking the prolog so a comment holding the word is not one.

    Nothing here reads a DTD, so nothing here resolves an entity, and no input reaches a file
    or a URL the document names.
    """
    position = 0
    while position < len(text):
        rest = text[position:]
        position += len(rest) - len(rest.lstrip())
        if text.startswith("<!--", position):
            end = text.find("-->", position)
            if end < 0:
                return
            position = end + 3
        elif text.startswith("<?", position):
            end = text.find("?>", position)
            if end < 0:
                return
            position = end + 2
        elif text[position : position + 9].upper() == "<!DOCTYPE":
            raise TransformError(
                "the input carries a <!DOCTYPE declaration, and convert.std reads XML without a DTD, "
                "because a DTD is where entities and the files they name enter a document"
            )
        else:
            return


def _read_xml(text: str, target_format: str) -> bytes:
    """Read the document as JSON, or stream the root's children as one record per line."""
    _refuse_doctype(text)
    if target_format == "ndjson":
        return "".join(f"{json.dumps(record, separators=(',', ':'))}\n" for record in _stream_records(text)).encode()
    root = _parse_xml(text)
    return _dump_json({root.tag: _element_value(root, root.tag)})


def _parse_xml(text: str) -> ET.Element:
    """Parse the whole document, naming where it stops being XML."""
    try:
        return ET.fromstring(text.encode())
    except ET.ParseError as error:
        raise TransformError(f"the input is not XML: {error}") from error


def _stream_records(text: str) -> Iterator[JsonValue]:
    """Walk the root's children with iterparse, dropping each one as soon as it is written."""
    events = ET.iterparse(io.BytesIO(text.encode()), events=("start", "end"))
    root: ET.Element | None = None
    depth = 0
    number = 0
    try:
        for event, element in events:
            if event == "start":
                if root is None:
                    root = element
                depth += 1
                continue
            depth -= 1
            if depth != 1 or root is None:
                continue
            number += 1
            if (root.text or "").strip():
                raise TransformError(
                    f"the element at {root.tag} has text beside its child elements, and the records "
                    f"xml to ndjson writes are those children"
                )
            yield _element_value(element, f"{root.tag}/{element.tag}[{number}]")
            # The root keeps every child the walk has seen, so it holds the whole document
            # unless each record is dropped once it is written.
            root.clear()
    except ET.ParseError as error:
        raise TransformError(f"the input is not XML: {error}") from error


def _element_value(element: ET.Element, path: str) -> JsonValue:
    """Read one element as its object, or as the string or null an element with nothing else is."""
    text = (element.text or "").strip()
    attributes: dict[str, JsonValue] = {f"{ATTRIBUTE_PREFIX}{name}": value for name, value in element.attrib.items()}
    children = list(element)
    if not children:
        if not attributes:
            return text or None
        return {**attributes, TEXT_KEY: text} if text else attributes
    if text or any((child.tail or "").strip() for child in children):
        raise TransformError(
            f"the element at {path} has text beside its child elements, and this mapping keeps an "
            f"element's text under {TEXT_KEY!r} only where the element has no children"
        )
    value: dict[str, JsonValue] = dict(attributes)
    for number, child in enumerate(children, start=1):
        read = _element_value(child, f"{path}/{child.tag}[{number}]")
        if child.tag not in value:
            value[child.tag] = read
        elif isinstance(value[child.tag], list):
            cast("list[JsonValue]", value[child.tag]).append(read)
        else:
            value[child.tag] = [value[child.tag], read]
    return value


def _write_xml(value: JsonValue) -> bytes:
    """Write one JSON object of a single key as the document that key names the root of."""
    if not isinstance(value, dict) or len(value) != 1:
        shape = f"an object of {len(value)} keys" if isinstance(value, dict) else _named(value)
        raise TransformError(
            f"json to xml writes one root element, so the input has to be an object of exactly one key "
            f"naming it, and this one is {shape}"
        )
    tag, content = next(iter(value.items()))
    root = _element(tag, content, f"$.{tag}")
    written: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return written + b"\n"


def _check_xml_name(name: str, path: str, what: str) -> None:
    """Refuse a key that is no XML name, because this mapping writes a key as a tag or an attribute."""
    if not XML_NAME.match(name):
        raise TransformError(f"the key {name!r} at {path} is no XML name, and this mapping writes a key as {what}")


def _element(tag: str, value: JsonValue, path: str) -> ET.Element:
    """Write one JSON value as the element its key names."""
    _check_xml_name(tag, path, "an element's tag")
    element = ET.Element(tag)
    if isinstance(value, dict):
        _fill_element(element, value, path)
        return element
    if isinstance(value, list):
        raise TransformError(
            f"the value at {path} is an array of arrays, and a tag repeated is as deep as a repeat goes"
        )
    element.text = _text(value, path)
    return element


def _text(value: JsonValue, path: str) -> str | None:
    """Write one scalar as element text or an attribute value, in its JSON spelling."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict | list):
        raise TransformError(
            f"the value at {path} is {_named(value)}, and an XML attribute and an element's text hold text"
        )
    return json.dumps(value)


def _fill_element(element: ET.Element, value: dict[str, JsonValue], path: str) -> None:
    """Fill an element from its object: attributes, then text or children, never both."""
    children = {key: item for key, item in value.items() if not key.startswith(ATTRIBUTE_PREFIX) and key != TEXT_KEY}
    if TEXT_KEY in value and children:
        raise TransformError(
            f"the object at {path} has both {TEXT_KEY!r} and child keys, and this mapping keeps an "
            f"element's text under {TEXT_KEY!r} only where the element has no children"
        )
    for key, item in value.items():
        if key.startswith(ATTRIBUTE_PREFIX):
            name = key[len(ATTRIBUTE_PREFIX) :]
            _check_xml_name(name, path, "an attribute's name")
            attribute = _text(item, _step(path, key))
            if attribute is None:
                raise TransformError(f"the attribute {key!r} at {path} is null, and an XML attribute holds text")
            element.set(name, attribute)
        elif key == TEXT_KEY:
            element.text = _text(item, _step(path, key))
    for key, item in children.items():
        _append_children(element, key, item, _step(path, key))


def _append_children(element: ET.Element, tag: str, value: JsonValue, path: str) -> None:
    """Append the child or children one key stands for, a list being that tag repeated."""
    if not isinstance(value, list):
        element.append(_element(tag, value, path))
        return
    if not value:
        raise TransformError(
            f"the value at {path} is an empty array, and no elements at all is no key at all; "
            f"drop the key to convert the object"
        )
    for index, item in enumerate(value):
        element.append(_element(tag, item, f"{path}[{index}]"))
