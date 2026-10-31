"""Dialect-agnostic column types: JSONB on PostgreSQL, JSON on SQLite, one declaration."""

from datetime import UTC, datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine.interfaces import Dialect

#: JSONB where the dialect has it, plain JSON elsewhere.
JsonDocument = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

#: An auto-incrementing 64-bit key; SQLite needs plain INTEGER to alias the rowid.
BigId = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


class UtcDateTime(sa.TypeDecorator[datetime]):
    """A timestamptz that stays timezone-aware on SQLite too.

    PostgreSQL round-trips ``timestamptz`` natively; SQLite has no timezone concept and hands
    back a naive datetime, which would make every ``available_at <= now`` comparison in the
    engine a runtime error.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Store every instant as UTC, whatever zone the caller handed over."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Return an aware instant, re-attaching UTC where the dialect dropped it."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


#: Every timestamp in the schema is timezone-aware, on both dialects.
Timestamp = UtcDateTime()


def storable_text(value: str) -> str:
    """Write a NUL and what UTF-8 cannot as its backslash escape, and leave everything else as it is.

    Text that has been through this once comes through it again unchanged.
    """
    return value.encode("utf-8", "backslashreplace").decode("utf-8").replace("\x00", "\\u0000")


class SaidText(sa.TypeDecorator[str]):
    """Text something said, which holds whatever it quoted of a run, a caller or a service.

    JSON can carry a lone surrogate, which no database driver can encode, and a NUL, which
    PostgreSQL's text refuses, so a quoted value holding either would fail the write that records
    it, and with it whatever else that transaction settles. Each is stored as its backslash escape.
    """

    impl = sa.Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Write a NUL and what UTF-8 cannot as its escape."""
        return None if value is None else storable_text(value)


class SaidString(sa.TypeDecorator[str]):
    """Bounded text something said, written as ``SaidText`` writes it and cut to the column's length.

    An escape is longer than the character it stands for, so text cut to fit before it was
    escaped can outgrow the column after.
    """

    impl = sa.String
    cache_ok = True

    def __init__(self, length: int) -> None:
        """Bound the column to ``length`` characters."""
        super().__init__(length)
        self.length = length

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        """Write a NUL and what UTF-8 cannot as its escape, and keep what fits."""
        return None if value is None else storable_text(value)[: self.length]


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    """List an enum's values."""
    return [member.value for member in enum_class]


def string_enum(enum_class: type[StrEnum], name: str, *, length: int = 32) -> sa.Enum:
    """Store an enum by its value in a checked VARCHAR, so both dialects agree."""
    return sa.Enum(
        enum_class,
        name=name,
        native_enum=False,
        length=length,
        validate_strings=True,
        values_callable=_enum_values,
    )
