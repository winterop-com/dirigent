"""Storing and reading named JSON Schemas: the resource behind ``dg schema`` and ``validate.schema``.

A schema an instance holds is LOCALLY AUTHORED, exactly like a pipeline or a connection: a
person writes the shape they expect a payload to have and applies it. It is never fetched or
introspected from anywhere. Because a schema is a JSON Schema in its own right, its identity
is read from the schema's own keywords rather than a dirigent envelope -- ``$id`` for the
code, ``title`` for the name, ``description`` for the description -- so what an instance
stores is a portable schema, not a wrapper around one.

The draft is JSON Schema 2020-12, the one every other validity check in this engine uses.
A schema is checked to be a valid schema of that draft before it is stored.
"""

import re
from uuid import UUID

import sqlalchemy as sa
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_common import JsonMap
from dirigent_core.models import Schema

#: The code a schema is given when it names none: a slug drawn from ``$id`` or a filename.
_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,199}$")


class SchemaRefused(Exception):
    """A schema that cannot be stored, and the reason a caller can show."""


def code_from_id(schema_id: str) -> str | None:
    """Derive a code from a schema's ``$id``: its last path segment, minus any extension.

    ``https://dirigent/schemas/org-unit.json`` and ``org-unit`` both yield ``org-unit``. A
    segment that is not a usable code yields nothing, and the caller falls back to a filename
    or refuses.
    """
    tail = schema_id.rstrip("/").rsplit("/", 1)[-1]
    tail = re.sub(r"\.(json|yaml|yml)$", "", tail)
    return tail if _CODE_PATTERN.match(tail) else None


def resolve_identity(
    body: JsonMap,
    *,
    code: str | None,
    name: str | None,
    description: str | None,
    fallback_code: str | None = None,
) -> tuple[str, str | None, str | None]:
    """Settle a schema's identity: what the caller gave, else the schema's own keywords.

    A code given explicitly wins; then ``$id``; then a fallback such as a filename stem. A
    schema that yields no code any of those ways is refused. ``title`` and ``description``
    fill name and description when the caller leaves them out.
    """
    chosen = code
    if chosen is None:
        schema_id = body.get("$id")
        if isinstance(schema_id, str):
            chosen = code_from_id(schema_id)
    if chosen is None and fallback_code is not None and _CODE_PATTERN.match(fallback_code):
        chosen = fallback_code
    if chosen is None:
        raise SchemaRefused(
            "this schema names no code: give one, or set $id, or store it from a file whose name is a code"
        )
    title = body.get("title")
    resolved_name = name if name is not None else (title if isinstance(title, str) else None)
    doc = body.get("description")
    resolved_description = description if description is not None else (doc if isinstance(doc, str) else None)
    return chosen, resolved_name, resolved_description


def check_valid_schema(body: JsonMap) -> None:
    """Refuse a body that is not itself a valid JSON Schema (Draft 2020-12).

    A stored schema that names its own ``$schema`` for another draft is the author's call and
    jsonschema honours it at validation time; this check, and this engine's default, is
    2020-12 -- the same draft ``validate.schema`` and the parameter check use.
    """
    try:
        Draft202012Validator.check_schema(body)
    except SchemaError as error:
        where = "/".join(str(part) for part in error.absolute_path)
        at = f" at {where}" if where else ""
        raise SchemaRefused(f"this is not a valid JSON Schema{at}: {error.message}") from error


async def find_schema(session: AsyncSession, code: str) -> Schema | None:
    """Read one stored schema by its code, or nothing when the instance holds none."""
    return (await session.execute(sa.select(Schema).where(Schema.code == code))).scalar_one_or_none()


async def store_schema(
    session: AsyncSession,
    body: JsonMap,
    *,
    code: str | None = None,
    name: str | None = None,
    description: str | None = None,
    fallback_code: str | None = None,
) -> Schema:
    """Validate a JSON Schema, settle its identity, and store it -- replacing one of the same code."""
    check_valid_schema(body)
    resolved_code, resolved_name, resolved_description = resolve_identity(
        body, code=code, name=name, description=description, fallback_code=fallback_code
    )
    existing = await find_schema(session, resolved_code)
    if existing is None:
        row = Schema(code=resolved_code, name=resolved_name, description=resolved_description, body=body)
        session.add(row)
        await session.flush()
        return row
    existing.name = resolved_name
    existing.description = resolved_description
    existing.body = body
    await session.flush()
    return existing


async def schema_codes(session: AsyncSession) -> set[str]:
    """Every schema code the instance holds, for the requires preflight."""
    rows = await session.execute(sa.select(Schema.code))
    return {code for (code,) in rows.all()}


async def all_schemas(session: AsyncSession) -> list[Schema]:
    """Every stored schema, newest first, for listing and export."""
    rows = await session.execute(sa.select(Schema).order_by(Schema.created_at.desc()))
    return list(rows.scalars())


async def delete_schema(session: AsyncSession, code: str) -> bool:
    """Remove a schema; report whether one was there to remove."""
    row = await find_schema(session, code)
    if row is None:
        return False
    await session.delete(row)
    return True


async def schema_by_id(session: AsyncSession, schema_id: UUID) -> Schema | None:
    """Read one stored schema by its uuid."""
    return await session.get(Schema, schema_id)
