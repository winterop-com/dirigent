"""Schemas: named JSON Schemas an instance holds, addressable by code and referenced by name.

A schema is locally authored, exactly like a pipeline or a connection: a person writes the
shape they expect a payload to have and applies it. Nothing here fetches or introspects a
schema from anywhere. Because a schema is a JSON Schema in its own right, its identity is
read from its own keywords -- ``$id`` for the code, ``title`` for the name, ``description``
for the description -- when a write does not give one, so what is stored is a portable
schema rather than a wrapper around one. A stored body is checked to be a valid JSON Schema
(Draft 2020-12) before anything lands.

A stored schema is named from inside a pipeline document's JSON -- under ``requires.schemas``,
and in every step config field its block declares as a schema reference -- so there is no row
to hang a foreign key on. The pipelines naming a code are read from each stored pipeline's
current version and ride on every response as ``used_by``. Removing a schema that has any is
refused; changing one is not, and the answer carries them so the caller decides with them in
view.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from fastapi import APIRouter, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.schemas import Page, SchemaIn, SchemaOut, SchemaUpdate
from dirigent_core.models import Schema
from dirigent_core.schemas import SchemaInUse, check_valid_schema, resolve_identity, schema_users
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.errors import Refusal
from dirigent_server.messages import NO_SCHEMA, SCHEMA_EXISTS
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip
from dirigent_server.security import AdminDep, PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["schemas"])


def render(row: Schema, used_by: Sequence[str] = ()) -> SchemaOut:
    """Render a stored schema for a response, with the pipelines that name it."""
    return SchemaOut(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        body=row.body,
        created_at=row.created_at,
        updated_at=row.updated_at,
        used_by=list(used_by),
    )


async def find(session: AsyncSession, code: str) -> Schema:
    """Read one stored schema by code, or 404."""
    row = (await session.execute(sa.select(Schema).where(Schema.code == code))).scalar_one_or_none()
    if row is None:
        raise Refusal(NO_SCHEMA, status=status.HTTP_404_NOT_FOUND, code=repr(code))
    return row


@router.get("/schemas", operation_id="listSchemas", summary="List schemas", response_model=Page[SchemaOut])
async def list_schemas(
    session: SessionDep,
    services: ServicesDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[SchemaOut]:
    """List every schema the instance holds, each with the pipelines that name it."""
    statement = sa.select(Schema).order_by(Schema.code).limit(limit + 1)
    if after is not None:
        statement = statement.where(Schema.code > after)
    rows = await session.execute(statement)
    users = await schema_users(session, services.host.catalog())
    found = [render(row, users.get(row.code, ())) for row in rows.scalars()]
    items, following = clip(found, limit, lambda row: row.code)
    return Page(items=items, next=following)


@router.post(
    "/schemas",
    operation_id="createSchema",
    summary="Store a schema",
    response_model=SchemaOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_schema(
    payload: SchemaIn, session: SessionDep, services: ServicesDep, principal: AdminDep
) -> SchemaOut:
    """Store a JSON Schema, taking its identity from its own keywords when the write gives none."""
    check_valid_schema(payload.body)
    code, name, description = resolve_identity(
        payload.body, code=payload.code, name=payload.name, description=payload.description
    )
    existing = (await session.execute(sa.select(Schema).where(Schema.code == code))).scalar_one_or_none()
    if existing is not None:
        raise Refusal(SCHEMA_EXISTS, status=status.HTTP_409_CONFLICT, code=repr(code))
    row = Schema(code=code, name=name, description=description, body=payload.body)
    session.add(row)
    await session.flush()
    users = await schema_users(session, services.host.catalog())
    return render(row, users.get(row.code, ()))


@router.get("/schemas/{code}", operation_id="getSchema", summary="Read a schema", response_model=SchemaOut)
async def get_schema(code: str, session: SessionDep, services: ServicesDep, principal: PrincipalDep) -> SchemaOut:
    """Read one schema by its code, with the pipelines that name it."""
    row = await find(session, code)
    users = await schema_users(session, services.host.catalog())
    return render(row, users.get(code, ()))


@router.patch("/schemas/{code}", operation_id="updateSchema", summary="Update a schema", response_model=SchemaOut)
async def update_schema(
    code: str, payload: SchemaUpdate, session: SessionDep, services: ServicesDep, principal: AdminDep
) -> SchemaOut:
    """Replace a schema's body or its labels; the code is fixed once minted.

    A field left out is left alone; a name or description sent as null is cleared. A body
    sent replaces the stored schema and is checked the same way a create's is.

    An edit is never refused for being depended on. Correcting a shape every pipeline should
    now validate against is what editing a stored schema is for, the code cannot be changed,
    and whether a new body still admits what a dependent pipeline sends is not a question a
    schema can be asked. So the answer carries the pipelines that name it and the caller
    decides; what is refused is removing the shape from under them, not changing it.
    """
    row = await find(session, code)
    if payload.changing("name"):
        row.name = payload.name
    if payload.changing("description"):
        row.description = payload.description
    if payload.body is not None:
        check_valid_schema(payload.body)
        row.body = payload.body
    await session.flush()
    users = await schema_users(session, services.host.catalog())
    return render(row, users.get(code, ()))


@router.delete(
    "/schemas/{code}",
    operation_id="deleteSchema",
    summary="Delete a schema",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schema(code: str, session: SessionDep, services: ServicesDep, principal: AdminDep) -> Response:
    """Remove a schema, refusing one a stored pipeline still names.

    Applying a document that names a schema the instance does not hold is already refused, so
    a delete that went through here would leave behind exactly the state no apply is allowed
    to create -- and the next apply of an untouched pipeline, or the next attempt of a run in
    flight, would be what discovered it. No foreign key can say so: a schema is named from
    inside a document's JSON, not by a row.
    """
    row = await find(session, code)
    named = (await schema_users(session, services.host.catalog())).get(code, [])
    if named:
        raise SchemaInUse(code, named)
    await session.delete(row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
