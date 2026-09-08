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
