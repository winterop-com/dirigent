"""Holding an answer under its bound, reading a long text a stretch at a time, and editing text in place."""

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from dirigent_mcp.answers import Edit, attempt_row, bounded, edited, pointed, size_of, window
from dirigent_mcp.messages import NARROW_AN_OUTPUT


def test_an_answer_that_fits_is_answered_as_it_is() -> None:
    answer = {"items": [{"code": "a"}], "next": "a"}
    assert bounded(answer, cap=1_000) is answer


def test_a_page_too_large_keeps_the_rows_that_fit_and_drops_its_next() -> None:
    rows = [{"code": f"row-{index}", "text": "x" * 100} for index in range(100)]

    cut = bounded({"items": rows, "next": "row-99"}, cap=4_000)

    assert size_of(cut) <= 4_000
    assert 0 < len(cut["items"]) < 100
    assert cut["items"] == rows[: len(cut["items"])]
    assert "next" not in cut
    assert f"limit={len(cut['items'])}" in cut["truncated"]


def test_a_read_too_large_is_cut_to_a_preview_saying_how_to_narrow_it() -> None:
    cut = bounded({"output": "y" * 10_000}, narrow=NARROW_AN_OUTPUT, cap=2_000)
    assert size_of(cut) <= 2_000
    assert cut["bytes"] > 10_000
    assert "`path`" in cut["truncated"]
    assert cut["preview"].startswith('{"output":"yyy')


def test_a_long_text_is_read_a_stretch_at_a_time_and_the_stretches_are_the_text() -> None:
    text = "".join(f"line {index}\n" for index in range(1_000))
    first = window(text, chars=1_000)
    second = window(text, first["next_offset"], chars=1_000)
    assert first["text"] + second["text"] == text[:2_000]
    assert first["total_chars"] == len(text)
    assert "next_offset" not in window(text, len(text) - 10, chars=1_000)


def test_an_attempt_shows_its_output_size_and_start_unless_asked_for_the_output() -> None:
    row = {"id": "a", "output": {"rows": list(range(500))}}
    shown = attempt_row(row, include_output=False)
    assert "output" not in shown
    assert shown["output_preview"].startswith('{"rows":[0,1,2')
    assert shown["output_bytes"] > len(shown["output_preview"])
    assert attempt_row(row, include_output=True) is row
    assert attempt_row({"id": "b"}, include_output=False) == {"id": "b"}


def test_a_pointer_reads_one_part_of_an_output() -> None:
    output = {"rows": [{"name": "first"}], "a/b": 1, "m~n": 2}
    assert pointed(output, "") is output
    assert pointed(output, "/rows/0/name") == "first"
    assert (pointed(output, "/a~1b"), pointed(output, "/m~0n")) == (1, 2)
    with pytest.raises(ToolError, match="reaches nothing"):
        pointed(output, "/rows/1")
    with pytest.raises(ToolError, match="not a JSON pointer"):
        pointed(output, "rows")


def test_edits_apply_in_turn() -> None:
    text = "one: 1\ntwo: 2\n"
    assert edited(text, [Edit(old="one: 1", new="one: 10"), Edit(old="one: 10\n", new="")]) == "two: 2\n"


def test_every_edit_that_misses_is_named_and_none_is_applied() -> None:
    with pytest.raises(ToolError) as refused:
        edited("a\na\nb\n", [Edit(old="b", new="c"), Edit(old="a", new="x"), Edit(old="z", new="y")])
    said = str(refused.value)
    assert "edit 1: its `old` text occurs 2 times" in said
    assert "edit 2: its `old` text does not occur" in said
    assert "edit 0" not in said
