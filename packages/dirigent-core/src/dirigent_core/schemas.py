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

import asyncio
import re
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import timedelta
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from jsonschema import Draft202012Validator, FormatChecker, ValidationError
from jsonschema.exceptions import SchemaError
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AuditAction, AuditSubject
from dirigent_client.schemas import Catalog, SchemaCheck, SchemaViolation
from dirigent_common import (
    EvaluationOverrun,
    Issue,
    JsonMap,
    Unresolvable,
    format_duration,
    reference_targets,
    schema_code_of,
    value_errors,
)
from dirigent_common.messages import TEXT_UNSTORABLE
from dirigent_common.storable import is_storable
from dirigent_core import audit
from dirigent_core.engine.definition import schemas_named
from dirigent_core.errors import DomainError
from dirigent_core.messages import (
    SCHEMA_IN_USE,
    SCHEMA_INVALID,
    SCHEMA_NO_CODE,
    SCHEMA_REFERENCE_UNRESOLVED,
    SCHEMA_REFERENCED,
    SCHEMA_VALUE_UNCHECKED,
)
from dirigent_core.models import Pipeline, PipelineVersion, Schema
from dirigent_core.schemaerrors import describe

#: The code a schema is given when it names none: a slug drawn from ``$id`` or a filename.
_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,199}$")


class SchemaRefused(DomainError):
    """A schema that cannot be stored, and the reason a caller can show."""


class SchemaReferenced(DomainError):
    """A schema was asked to be removed while another stored schema still references it."""

    status = 409
    message = SCHEMA_REFERENCED

    def __init__(self, code: str, referrers: Sequence[str]) -> None:
        """Say which schemas reference it, so what has to change is in the refusal."""
        named = ", ".join(referrers)
        said = f"schema {named}" if len(referrers) == 1 else f"schemas {named}"
        super().__init__(code=repr(code), referrers=said)
        self.referrers = list(referrers)


class SchemaInUse(DomainError):
    """A schema was asked to be removed while a stored pipeline still names it."""

    status = 409
    message = SCHEMA_IN_USE

    def __init__(self, code: str, pipelines: Sequence[str]) -> None:
        """Say which pipelines name it, so what has to change is in the refusal."""
        named = ", ".join(pipelines)
        users = f"pipeline {named}" if len(pipelines) == 1 else f"pipelines {named}"
        super().__init__(code=repr(code), count=len(pipelines), pipelines=named, users=users)
        self.pipelines = list(pipelines)


def code_from_id(schema_id: str) -> str | None:
    """Derive a code from a schema's ``$id``: its last path segment, minus any extension.

    ``https://dirigent/schemas/org-unit.json`` and ``org-unit`` both yield ``org-unit``. A
    segment that is not a usable code yields nothing, and the caller falls back to a filename
    or refuses.
    """
    return schema_code_of(schema_id)


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
    fill name and description when the caller leaves them out, and either is refused when no
    database stores it as written.
    """
    chosen = code
    if chosen is None:
        schema_id = body.get("$id")
        if isinstance(schema_id, str):
            chosen = code_from_id(schema_id)
    if chosen is None and fallback_code is not None and _CODE_PATTERN.match(fallback_code):
        chosen = fallback_code
    if chosen is None:
        raise SchemaRefused(SCHEMA_NO_CODE)
    title = body.get("title")
    resolved_name = name if name is not None else (title if isinstance(title, str) else None)
    doc = body.get("description")
    resolved_description = description if description is not None else (doc if isinstance(doc, str) else None)
    unstorable = [
        Issue.of(TEXT_UNSTORABLE, location=field)
        for field, text in (("name", resolved_name), ("description", resolved_description))
        if text is not None and not is_storable(text)
    ]
    if unstorable:
        raise SchemaRefused(TEXT_UNSTORABLE, problems=unstorable)
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
        raise SchemaRefused(SCHEMA_INVALID, at=at, detail=error.message) from error


#: How long checking one value may take, which is a ``validate.schema`` step's own default.
CHECK_WITHIN: Final = timedelta(seconds=10)

#: How many failures one check lists; the rest are counted.
MAX_VIOLATIONS: Final = 100


async def check_value(
    schema: JsonMap,
    value: JsonValue,
    format_checker: FormatChecker,
    held: Mapping[str, JsonMap] | None = None,
) -> SchemaCheck:
    """Check a value against a schema with the evaluation a ``validate.schema`` step makes, naming every failure.

    The schema is not checked here: a stored one was checked when it was stored, and a body is
    checked by the caller first. A ``$ref`` is followed inside the schema and into ``held``, the
    schemas the instance holds by code, which is what a run does with the ones it pinned.
    """
    lookup: Callable[[str], JsonMap | None] = (held or {}).get
    stopped = threading.Event()
    try:
        errors = await asyncio.to_thread(
            value_errors,
            schema,
            value,
            format_checker=format_checker,
            within=CHECK_WITHIN,
            stopped=stopped,
            held=lookup,
        )
    except Unresolvable as error:
        raise SchemaRefused(SCHEMA_REFERENCE_UNRESOLVED, ref=error.ref) from error
    except EvaluationOverrun as error:
        raise SchemaRefused(SCHEMA_VALUE_UNCHECKED, timeout=format_duration(error.within)) from error
    finally:
        stopped.set()
    listed = [_violation(error) for error in errors[:MAX_VIOLATIONS]]
    return SchemaCheck(valid=not errors, errors=listed, omitted=max(len(errors) - MAX_VIOLATIONS, 0))


def _violation(error: ValidationError) -> SchemaViolation:
    """One failure as the wire carries it, said in the words a refused value is said in."""
    return SchemaViolation(
        at=_pointer(error.absolute_path),
        keyword=str(error.validator),
        schema_at=_pointer(error.absolute_schema_path),
        message=describe(error),
    )


def _pointer(parts: Iterable[object]) -> str:
    """Write a path as a JSON Pointer, escaping ``~`` and ``/`` in each part."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


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
        await audit.record(session, AuditAction.CREATED, AuditSubject.SCHEMA, code=row.code, subject_id=row.id)
        return row
    before = schema_fields(existing)
    existing.name = resolved_name
    existing.description = resolved_description
    existing.body = body
    await session.flush()
    await record_schema_update(session, existing, before)
    return existing


def schema_fields(row: Schema) -> dict[str, object]:
    """What an edit of a stored schema may change, for naming the fields it did."""
    return {"name": row.name, "description": row.description, "body": row.body}


async def record_schema_update(session: AsyncSession, row: Schema, before: dict[str, object]) -> None:
    """Journal an edit of a stored schema, naming the fields it changed, when it changed any."""
    fields = audit.changed(before, schema_fields(row))
    if fields:
        await audit.record(
            session, AuditAction.UPDATED, AuditSubject.SCHEMA, code=row.code, subject_id=row.id, fields=fields
        )


async def schema_codes(session: AsyncSession) -> set[str]:
    """Every schema code the instance holds, for the requires preflight."""
    rows = await session.execute(sa.select(Schema.code))
    return {code for (code,) in rows.all()}


async def held_bodies(session: AsyncSession) -> dict[str, JsonMap]:
    """The body of every schema the instance holds, by code: what a ``$ref`` may reach."""
    rows = await session.execute(sa.select(Schema.code, Schema.body))
    return {code: dict(body) for code, body in rows.all()}


def reference_closure(codes: Iterable[str], bodies: Mapping[str, JsonMap]) -> tuple[set[str], set[str]]:
    """The codes reached from ``codes`` through ``$ref``, the starting ones included, and what reaches nothing.

    Answers what is held among them, and every starting code and reference that reaches no
    schema in ``bodies``, so a caller can pin the first and refuse over the second.
    """
    reached: set[str] = set()
    missing: set[str] = set()
    waiting = list(codes)
    while waiting:
        code = waiting.pop()
        if code in reached or code in missing:
            continue
        body = bodies.get(code)
        if body is None:
            missing.add(code)
            continue
        reached.add(code)
        targets, unreached = reference_targets(body, bodies.get)
        missing |= unreached
        waiting.extend(targets)
    return reached, missing


async def schema_referrers(session: AsyncSession, code: str) -> list[str]:
    """Every other stored schema whose ``$ref`` names this code."""
    bodies = await held_bodies(session)
    return sorted(
        other for other, body in bodies.items() if other != code and code in reference_targets(body, bodies.get)[0]
    )


async def schema_users(session: AsyncSession, catalog: Catalog) -> dict[str, list[str]]:
    """Which stored pipelines check against each schema code, by name or through another's ``$ref``.

    A pipeline naming a schema that references another checks against both, so it is a user of
    each.

    Only each pipeline's current version is asked. A past version is history: holding a schema
    back because a version nobody applies any more once named it would make a code undeletable
    for the life of the instance.

    The documents are read and walked here rather than queried into, so a JSON operator no
    dialect shares is never reached for and SQLite and PostgreSQL answer the same thing.
    """
    statement = (
        sa.select(Pipeline.code, PipelineVersion.document)
        .join(PipelineVersion, PipelineVersion.pipeline_id == Pipeline.id)
        .where(PipelineVersion.version == Pipeline.current_version)
    )
    bodies = await held_bodies(session)
    users: dict[str, set[str]] = {}
    for code, document in (await session.execute(statement)).all():
        named = schemas_named(document, catalog)
        reached, _ = reference_closure(named, bodies)
        for one in named | reached:
            users.setdefault(one, set()).add(code)
    return {named: sorted(pipelines) for named, pipelines in users.items()}


async def all_schemas(session: AsyncSession) -> list[Schema]:
    """Every stored schema, newest first, for listing and export."""
    rows = await session.execute(sa.select(Schema).order_by(Schema.created_at.desc()))
    return list(rows.scalars())


async def delete_schema(session: AsyncSession, code: str) -> bool:
    """Remove a schema; report whether one was there to remove.

    Raises:
        SchemaReferenced: Another stored schema references it with ``$ref``.
    """
    row = await find_schema(session, code)
    if row is None:
        return False
    referrers = await schema_referrers(session, code)
    if referrers:
        raise SchemaReferenced(code, referrers)
    await session.delete(row)
    await session.flush()
    await audit.record(session, AuditAction.DELETED, AuditSubject.SCHEMA, code=code, subject_id=row.id)
    return True


async def schema_by_id(session: AsyncSession, schema_id: UUID) -> Schema | None:
    """Read one stored schema by its uuid."""
    return await session.get(Schema, schema_id)
