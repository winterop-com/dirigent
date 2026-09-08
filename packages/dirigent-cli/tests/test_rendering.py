"""The console rendering of a record: one grammar, whatever colour it is rendered in.

These call the renderer directly over known records. Nothing here asks a terminal what it
is: colour is named on each call, so a line that only parses without colour is a failure
here rather than a surprise on somebody's screen.
"""

import io
from typing import Any

import pytest
from rich.console import Console

from clisupport import LINE, plain
from dirigent_cli.output import flagged
from dirigent_cli.stream import paint, shorten, track_steps, use_scratch_prefix
from dirigent_core.protocol import Record, console, make

AT = "2026-01-01T12:00:00.000+00:00"

SCRATCH = "file:///scratch/runs/01a0"


@pytest.fixture(autouse=True)
def _tracked() -> None:  # pyright: ignore[reportUnusedFunction]
    """Give the steps their colours, which is what makes a painted line painted."""
    track_steps(["fetch", "push"])


def coloured(line: str) -> str:
    """Render one already-painted line the way a terminal that wants colour would get it.

    Every one of these is named rather than detected, NO_COLOR included: this is the case a
    test suite reading a pipe would otherwise never reach.
    """
    written = io.StringIO()
    console = Console(file=written, force_terminal=True, color_system="truecolor", width=300, no_color=False)
    console.print(line, soft_wrap=True, highlight=False)
    return written.getvalue().rstrip("\n")


def log(**fields: Any) -> Record:
    """One log record, of the shape a block writes."""
    return make("log", at=AT, step="fetch", message="http call", **fields)


def test_a_line_names_when_at_what_level_of_what_kind_and_from_where() -> None:
    found = LINE.match(console(log(status=200), local=False))
    assert found is not None
    assert found.group("at") == AT
    assert found.group("level") == "info"
    assert found.group("kind") == "log"
    assert found.group("source") == "fetch"
    assert found.group("message") == "http call"
    assert found.group("fields") == "status=200"


def test_a_painted_line_parses_the_same_as_an_unpainted_one() -> None:
    """Colour is decoration: strip it and the grammar is untouched."""
    record = log(status=200)
    rendered = coloured(console(record, paint=paint, local=False))
    assert "\x1b[" in rendered, "this is the case that only happens where colour was wanted"
    assert plain(rendered) == console(record, local=False)
    assert LINE.match(plain(rendered)) is not None


def test_a_level_that_is_not_routine_is_marked_and_still_parses() -> None:
    warned = make("log", at=AT, level="warning", step="fetch", message="careful")
    rendered = coloured(console(warned, paint=paint, local=False))
    assert rendered != coloured(console(warned, local=False)), "a warning is marked"
    found = LINE.match(plain(rendered))
    assert found is not None
    assert found.group("level") == "warning"


def test_an_unknown_kind_of_record_still_renders_as_a_line() -> None:
    """A record from a newer dirigent reads as a line rather than as nothing."""
    found = LINE.match(console(make("weather", at=AT, step="fetch", message="it rained", mm=4), local=False))
    assert found is not None
    assert found.group("kind") == "weather"
    assert found.group("fields") == "mm=4"


def test_two_artifacts_under_one_prefix_stay_two_values() -> None:
    """Shortening stops where the value stops being distinguishable from another one."""
    use_scratch_prefix(SCRATCH)
    try:
        first = console(shorten(make("output", at=AT, step="fetch", artifact=f"{SCRATCH}/first.json")), local=False)
        second = console(shorten(make("output", at=AT, step="push", artifact=f"{SCRATCH}/second.json")), local=False)
    finally:
        use_scratch_prefix(None)
    assert "artifact=first.json" in first
    assert "artifact=second.json" in second
    assert SCRATCH not in first, "the prefix they share is stated once, on the run's own event"


def test_a_uri_outside_the_runs_prefix_is_left_whole() -> None:
    use_scratch_prefix(SCRATCH)
    try:
        elsewhere = console(shorten(make("output", at=AT, step="fetch", artifact="s3://bucket/a.json")), local=False)
    finally:
        use_scratch_prefix(None)
    assert "artifact=s3://bucket/a.json" in elsewhere


def test_a_step_that_warned_is_flagged_beside_its_name() -> None:
    assert "1 warn" in plain(coloured(flagged(1)))
    assert flagged(0) == ""


def test_the_origin_bracket_sits_in_one_column_whatever_the_record_is() -> None:
    """Columns are padded so a reader's eye finds the kind in the same place on every row."""
    stream = [
        make("run", at=AT, message="started", pipeline="demo"),
        make("step", at=AT, step="fetch", message="queued", block="http.request"),
        log(status=200),
        make("step", at=AT, step="push", message="succeeded", block="storage.copy"),
    ]
    matched = [LINE.match(console(record, local=False)) for record in stream]
    assert all(found is not None for found in matched)
    origins = {found.start("kind") for found in matched if found is not None}
    assert len(origins) == 1, f"the origin bracket drifts between rows: {origins}"
