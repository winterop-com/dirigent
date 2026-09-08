"""One record protocol: what a line promises, and that NDJSON survives a round trip."""

import json
import re
import shlex
from datetime import UTC, datetime
from typing import Any

from dirigent_core.protocol import (
    POSITIONAL,
    PROTOCOL_VERSION,
    RESERVED,
    VERSION_KEY,
    as_json,
    console,
    make,
    parse,
    render,
)

AT = datetime(2026, 1, 1, 18, 22, 23, 69000, tzinfo=UTC)

#: The console grammar, as anything consuming it has to implement it.
LINE = re.compile(
    r"^(?P<at>\S+)\s+\[(?P<level>\w+)\s*\]\s+(?P<message>.*?)"
    r"\s+\[(?P<kind>\w+)(?:\s+(?P<source>\S+))?\]\s*(?P<fields>.*)$"
)


def columns(line: str) -> tuple[str, str, str, str | None, str, dict[str, str]]:
    """Take one console line apart: its four parts, then whatever fields it carries."""
    match = LINE.match(line)
    assert match is not None, f"the line does not parse: {line!r}"
    fields = dict(token.split("=", 1) for token in shlex.split(match["fields"]))
    return match["at"], match["level"], match["kind"], match["source"], match["message"], fields


def test_a_record_leads_with_the_keys_the_protocol_owns() -> None:
    record = make("log", at=AT, step="fetch", message="http call", status=200)
    assert list(record)[: len(POSITIONAL) + 1] == [VERSION_KEY, *POSITIONAL]
    assert record[VERSION_KEY] == PROTOCOL_VERSION
    assert record["status"] == 200


def test_a_field_cannot_shadow_a_key_a_parser_reads_the_record_by() -> None:
    """A block naming a field `level` must not be able to change what the line says it is."""
    written: dict[str, Any] = {"kind": "invented", "v": 99}
    record = make("log", at=AT, message="careful", **written)
    assert record["kind"] == "log", "the record's own kind stands"
    assert record[VERSION_KEY] == PROTOCOL_VERSION
    assert record["fields.kind"] == "invented"
    assert record["fields.v"] == 99
    line = console(make("log", at=AT, step="x", message="careful", fields={"level": "sneaky", "count": 2}))
    assert columns(line)[1] == "info", "and so does the level column, whatever a block called its field"
    assert columns(line)[5] == {"fields.level": "sneaky", "count": "2"}


def test_every_console_line_has_the_same_four_parts_then_its_fields() -> None:
    at, level, kind, source, message, fields = columns(
        console(make("log", at=AT, step="fetch", message="http call", status=200, url="https://example.org/get"))
    )
    assert level == "info"
    assert kind == "log"
    assert source == "fetch"
    assert message == "http call"
    assert fields == {"status": "200", "url": "https://example.org/get"}
    assert at.startswith("2026-01-01T")


def test_a_line_about_the_run_itself_names_only_its_kind() -> None:
    """With no step to name, the origin bracket holds the kind and nothing else."""
    _, _, kind, source, message, fields = columns(console(make("run", at=AT, message="started")))
    assert (kind, source, message, fields) == ("run", None, "started", {})


def test_a_fan_out_element_is_named_beside_the_kind() -> None:
    assert columns(console(make("step", at=AT, step="push", item="east", message="running")))[3] == "push[east]"


def test_a_value_that_would_read_as_two_tokens_is_quoted() -> None:
    line = console(make("log", at=AT, step="greet", message="said it", text="two words", bare="one"))
    assert '"two words"' in line
    assert columns(line)[5] == {"text": "two words", "bare": "one"}


def test_nothing_is_elided_however_many_fields_a_record_carries() -> None:
    fields: dict[str, Any] = {f"field_{index}": index for index in range(12)}
    assert columns(console(make("log", at=AT, step="x", message="m", **fields)))[5] == {
        name: str(value) for name, value in fields.items()
    }


def test_a_long_value_is_carried_whole() -> None:
    """A value cut in half is a value nobody can parse or paste, however wide the terminal is."""
    url = "https://example.org/" + "x" * 400
    assert url in console(make("log", at=AT, step="fetch", message="http call", url=url))


def test_a_record_survives_the_round_trip_through_ndjson() -> None:
    record = make(
        "step",
        at=AT,
        level="warning",
        step="push",
        item="east",
        message="failed",
        block="http.request",
        attempt=2,
        duration_ms=308,
        body={"nested": ["a", "b"], "count": 2},
        flag=True,
    )
    read = parse(render(record, "json"))
    assert read is not None
    for name in (*POSITIONAL, "block", "attempt", "duration_ms", "flag"):
        assert read[name] == record[name], name
    assert read["body"] == record["body"]
    assert read[VERSION_KEY] == PROTOCOL_VERSION


def test_the_json_spelling_is_one_object_per_line() -> None:
    body = json.loads(as_json(make("log", at=AT, step="fetch", message="http call", status=200)))
    assert body["kind"] == "log" and body["message"] == "http call" and body["status"] == 200
    assert body[VERSION_KEY] == PROTOCOL_VERSION


def test_a_newline_inside_a_record_stays_inside_its_json_string() -> None:
    line = as_json(make("log", at=AT, message="first\nsecond"))
    assert "\n" not in line
    assert json.loads(line)["message"] == "first\nsecond"


def test_a_line_that_is_not_ours_is_reported_as_such_rather_than_guessed_at() -> None:
    """A real log interleaves, so a caller passes a foreign line through untouched."""
    assert parse("") is None
    assert parse("not a record at all") is None
    assert parse('{"unrelated": true}') is None
    assert parse("[info] something a library printed") is None


def test_a_process_log_record_parses_as_the_protocol_reads_it() -> None:
    """Structlog spells the message `event` and the moment `timestamp`; a stored log has both."""
    read = parse('{"event":"worker started","timestamp":"2026-01-01T18:22:23.069Z","level":"info","worker":"local"}')
    assert read is not None
    assert read["message"] == "worker started"
    assert read["at"] == "2026-01-01T18:22:23.069Z"
    assert read["worker"] == "local"
    assert "event" not in read, "the key is renamed, not copied, or a rendering prints it twice"
    assert "timestamp" not in read


def test_every_reserved_name_is_a_key_every_record_carries() -> None:
    """Reserving a name an emitter is free to use would namespace an ordinary field."""
    assert set(RESERVED) == set(make("step", at=AT, step="x", message="m"))
