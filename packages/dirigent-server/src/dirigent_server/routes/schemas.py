"""Schemas: named JSON Schemas an instance holds, addressable by code and referenced by name.

A schema is locally authored, exactly like a pipeline or a connection: a person writes the
shape they expect a payload to have and applies it. Nothing here fetches or introspects a
schema from anywhere. Because a schema is a JSON Schema in its own right, its identity is
read from its own keywords -- ``$id`` for the code, ``title`` for the name, ``description``
for the description -- when a write does not give one, so what is stored is a portable
schema rather than a wrapper around one. A stored body is checked to be a valid JSON Schema
(Draft 2020-12) before anything lands.
"""

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.schemas import Page, SchemaIn, SchemaOut, SchemaUpdate
from dirigent_core.models import Schema
from dirigent_core.schemas import SchemaRefused, check_valid_schema, resolve_identity
from dirigent_server.dependencies import SessionDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip
from dirigent_server.security import AdminDep, PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["schemas"])


def render(row: Schema) -> SchemaOut:
    """Render a stored schema for a response."""
    return SchemaOut(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        body=row.body,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def find(session: AsyncSession, code: str) -> Schema:
    """Read one stored schema by code, or 404."""
    row = (await session.execute(sa.select(Schema).where(Schema.code == code))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no schema coded {code!r}")
    return row


@router.get("/schemas", operation_id="listSchemas", summary="List schemas", response_model=Page[SchemaOut])
async def list_schemas(
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[SchemaOut]:
    """List every schema the instance holds."""
    statement = sa.select(Schema).order_by(Schema.code).limit(limit + 1)
    if after is not None:
        statement = statement.where(Schema.code > after)
    rows = await session.execute(statement)
    found = [render(row) for row in rows.scalars()]
    items, following = clip(found, limit, lambda row: row.code)
    return Page(items=items, next=following)


@router.post(
    "/schemas",
    operation_id="createSchema",
    summary="Store a schema",
    response_model=SchemaOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_schema(payload: SchemaIn, session: SessionDep, principal: AdminDep) -> SchemaOut:
    """Store a JSON Schema, taking its identity from its own keywords when the write gives none."""
    try:
        check_valid_schema(payload.body)
        code, name, description = resolve_identity(
            payload.body, code=payload.code, name=payload.name, description=payload.description
        )
    except SchemaRefused as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    existing = (await session.execute(sa.select(Schema).where(Schema.code == code))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"a schema coded {code!r} exists")
    row = Schema(code=code, name=name, description=description, body=payload.body)
    session.add(row)
    await session.flush()
    return render(row)


@router.get("/schemas/{code}", operation_id="getSchema", summary="Read a schema", response_model=SchemaOut)
async def get_schema(code: str, session: SessionDep, principal: PrincipalDep) -> SchemaOut:
    """Read one schema by its code."""
    return render(await find(session, code))


@router.patch("/schemas/{code}", operation_id="updateSchema", summary="Update a schema", response_model=SchemaOut)
async def update_schema(code: str, payload: SchemaUpdate, session: SessionDep, principal: AdminDep) -> SchemaOut:
    """Replace a schema's body or its labels; the code is fixed once minted.

    A field left out is left alone; a name or description sent as null is cleared. A body
    sent replaces the stored schema and is checked the same way a create's is.
    """
    row = await find(session, code)
    if payload.changing("name"):
        row.name = payload.name
    if payload.changing("description"):
        row.description = payload.description
    if payload.body is not None:
        try:
            check_valid_schema(payload.body)
        except SchemaRefused as error:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
        row.body = payload.body
    await session.flush()
    return render(row)


@router.delete(
    "/schemas/{code}",
    operation_id="deleteSchema",
    summary="Delete a schema",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_schema(code: str, session: SessionDep, principal: AdminDep) -> Response:
    """Remove a schema."""
    await session.delete(await find(session, code))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
