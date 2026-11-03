"""Keeping every answer an agent reads under one size, and editing a document's text in place."""

import json
from collections.abc import Sequence
from typing import Any, Final, cast

import pydantic_core
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict

from dirigent_common import Message
from dirigent_mcp.messages import (
    EDIT_AMBIGUOUS,
    EDIT_EMPTY,
    EDIT_NOT_FOUND,
    EDITS_REFUSED,
    NARROW_A_LISTING,
    NARROW_A_READ,
    POINTER_INVALID,
    POINTER_MISSES,
    TRUNCATED_ANSWER,
    TRUNCATED_PAGE,
)

#: The most bytes of JSON one answer carries; anything larger is cut, saying how to narrow it.
MAX_ANSWER_BYTES: Final = 48_000

#: The most characters of a document one answer carries; `next_offset` reads on from there.
WINDOW_CHARS: Final = 24_000

#: How much of an attempt's output a listing shows in place of the output itself.
PREVIEW_CHARS: Final = 200

#: Room left beside a page's rows for the note that says it was cut.
PAGE_SLACK: Final = 512


class Edit(BaseModel):
    """One exact replacement: `old` must occur exactly once in the text it is applied to."""

    model_config = ConfigDict(frozen=True)

    old: str
    new: str


def encoded(value: Any) -> str:
    """A value's JSON, compact, as a preview quotes it."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def size_of(value: Any) -> int:
    """How many bytes a value takes as the text of an answer, which MCP indents by two."""
    return len(pydantic_core.to_json(value, fallback=str, indent=2))


def bounded(answer: Any, *, narrow: Message | None = None, cap: int = MAX_ANSWER_BYTES) -> Any:
    """Answer as it is when it fits under ``cap``; else a page's leading rows, or the start of its JSON.

    A page that is cut loses its `next`, which would skip the rows left out, and says which
    `limit` asks for the rows that fit with a `next` of their own. ``narrow`` is what the note
    says to do instead, a listing's or a read's by default.
    """
    size = size_of(answer)
    if size <= cap:
        return answer
    fields = cast(dict[str, Any], answer) if isinstance(answer, dict) else {}
    page = isinstance(fields.get("items"), list)
    if narrow is None:
        narrow = NARROW_A_LISTING if page else NARROW_A_READ
    if page:
        rows = cast(list[Any], fields["items"])
        rest = {key: value for key, value in fields.items() if key not in {"items", "next"}}
        room = cap - size_of({**rest, "items": []}) - PAGE_SLACK
        kept = 0
        for row in rows:
            room -= size_of(row) + 1
            if room < 0:
                break
            kept += 1
        while kept:
            cut = {
                **rest,
                "items": rows[:kept],
                "truncated": TRUNCATED_PAGE.render(shown=kept, total=len(rows), cap=cap),
            }
            if size_of(cut) <= cap:
                return cut
            kept = kept * 9 // 10
    note = TRUNCATED_ANSWER.render(size=size, cap=cap, narrow=narrow.render())
    text = encoded(answer)
    chars = cap // 2
    while True:
        cut = {"truncated": note, "bytes": size, "preview": text[:chars]}
        if size_of(cut) <= cap:
            return cut
        chars //= 2


def window(text: str, offset: int = 0, *, chars: int = WINDOW_CHARS) -> dict[str, Any]:
    """One stretch of a long text, from ``offset``, with where the next one starts when there is more."""
    start = max(offset, 0)
    end = start + chars
    shown: dict[str, Any] = {"text": text[start:end], "offset": start, "total_chars": len(text)}
    if end < len(text):
        shown["next_offset"] = end
    return shown


def attempt_row(row: dict[str, Any], *, include_output: bool) -> dict[str, Any]:
    """An attempt as a listing shows it: its output's size and opening characters, or the output itself."""
    if include_output or "output" not in row:
        return row
    shown = {key: value for key, value in row.items() if key != "output"}
    text = encoded(row["output"])
    shown["output_bytes"] = len(text.encode())
    shown["output_preview"] = text[:PREVIEW_CHARS]
    return shown


def pointed(value: Any, path: str) -> Any:
    """The part of a JSON value an RFC 6901 pointer names; the empty pointer names all of it."""
    if path == "":
        return value
    if not path.startswith("/"):
        raise ToolError(POINTER_INVALID.render(path=path))
    reached: Any = value
    for raw in path[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(reached, dict):
            mapping = cast(dict[str, object], reached)
            if token in mapping:
                reached = mapping[token]
                continue
        elif isinstance(reached, list):
            items = cast(list[object], reached)
            if token.isdigit() and int(token) < len(items):
                reached = items[int(token)]
                continue
        raise ToolError(POINTER_MISSES.render(path=path, token=token))
    return reached


def edited(text: str, edits: Sequence[Edit]) -> str:
    """Apply each edit in turn, or refuse them all, naming every one that does not quote its text exactly once."""
    working = text
    problems: list[str] = []
    for index, edit in enumerate(edits):
        if not edit.old:
            problems.append(EDIT_EMPTY.render(index=index))
            continue
        count = working.count(edit.old)
        if count == 0:
            problems.append(EDIT_NOT_FOUND.render(index=index))
        elif count > 1:
            problems.append(EDIT_AMBIGUOUS.render(index=index, count=count))
        else:
            working = working.replace(edit.old, edit.new, 1)
    if problems:
        raise ToolError(EDITS_REFUSED.render(problems="; ".join(problems)))
    return working
