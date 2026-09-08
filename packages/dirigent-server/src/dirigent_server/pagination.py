"""One envelope for every listing, and the keyset walk behind it.

Every listing answers ``{"items": [...], "next": <cursor or null>}``. ``limit`` bounds a page
at 500 and defaults to 50; ``after`` carries the cursor a previous page's ``next`` gave out.
A cursor is opaque to the caller and is the sort key of the last row returned, so a listing
selects ``limit + 1`` rows past it in its own order, answers ``limit`` of them, and says
``next`` only when the extra row existed. A cursor that does not parse is a 422.
"""

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import HTTPException, Query, status

DEFAULT_PAGE = 50

MAX_PAGE = 500

LimitParam = Annotated[int, Query(ge=1, le=MAX_PAGE, description="How many rows to return.")]

AfterParam = Annotated[str | None, Query(description="Continue from a previous page's next cursor.")]


def clip[T](rows: list[T], limit: int, key: Callable[[T], object]) -> tuple[list[T], str | None]:
    """Cut a ``limit + 1`` selection down to the page, and name the cursor that continues it."""
    page = rows[:limit]
    if len(rows) <= limit or not page:
        return page, None
    return page, str(key(page[-1]))


def uuid_cursor(after: str | None) -> UUID | None:
    """Read an id cursor, refusing anything that is not one."""
    if after is None:
        return None
    try:
        return UUID(after)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"after={after!r} is not a cursor this listing gave out",
        ) from error


def int_cursor(after: str | None, *, name: str = "after") -> int | None:
    """Read a numeric cursor, refusing anything that is not one."""
    if after is None:
        return None
    try:
        return int(after)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{name}={after!r} is not a cursor this listing gave out",
        ) from error
