"""Helpers the CLI tests share.

A test that asserts on what a command did reads the records it emitted; one that asserts on
how a command reads reads them through :func:`plain`, so no assertion depends on whether the
stream was decorated.
"""

import json
import re
from typing import Any, cast

#: The stream's grammar, as anything consuming a console line has to implement it: when, at
#: what level, what it said, what it came from, and then its fields. The origin bracket holds
#: the kind and, when the line has one, the step and the element it is working on.
LINE = re.compile(
    r"^(?P<at>\S+)\s+\[(?P<level>\w+)\s*\]\s+(?P<message>.*?)"
    r"\s+\[(?P<kind>\w+)(?:\s+(?P<source>\S+))?\]\s*(?P<fields>.*)$"
)

#: One ANSI escape sequence, which decoration puts between the characters an assertion looks
#: for. Colour, weight, and reset are all the same shape.
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """Read rendered output as the text it says, whatever styling was applied to it."""
    return ANSI.sub("", text)


def records(stdout: str) -> list[dict[str, Any]]:
    """Read an NDJSON stream back: one JSON object per line, in the order they were written."""
    return [cast("dict[str, Any]", json.loads(line)) for line in stdout.splitlines() if line.strip()]


def of_kind(stream: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    """Take the records of one kind, which is the field a reader reacts to."""
    return [record for record in stream if record.get("kind") == kind]


def rows(stdout: str, kind: str | None = None) -> list[dict[str, Any]]:
    """Read a listing back: the row each record carries, in the order they were written."""
    stream = records(stdout)
    wanted = stream if kind is None else of_kind(stream, kind)
    return [cast("dict[str, Any]", record["fields"]) for record in wanted]


def asking_for_the_rendering(argv: list[str]) -> list[str]:
    """Ask for the console rendering, for a test that reads one.

    NDJSON is what a command writes unasked, so a test about how something reads has to say
    so. A test that names an output of its own keeps it.
    """
    if any(item in {"-o", "--output", "--json"} for item in argv):
        return argv
    return ["-o", "console", *argv]


def messages(stdout: str, kind: str | None = None) -> list[str]:
    """Read what a stream said: the message of every record, or of every record of one kind."""
    stream = records(stdout)
    wanted = stream if kind is None else of_kind(stream, kind)
    return [str(record.get("message", "")) for record in wanted]


def closing(stdout: str) -> dict[str, Any]:
    """Take the last record a stream carries, which is where a command says how it ended."""
    stream = records(stdout)
    assert stream, "the command wrote no records at all"
    return stream[-1]


def only(stdout: str, kind: str) -> dict[str, Any]:
    """Take the one record of a kind, refusing a stream that carries none or several."""
    found = of_kind(records(stdout), kind)
    assert len(found) == 1, f"expected one {kind} record, got {len(found)}"
    return found[0]


def refusal(stdout: str) -> dict[str, Any]:
    """Take the problem record a refused command wrote, whoever decided to refuse."""
    return only(stdout, "error")
