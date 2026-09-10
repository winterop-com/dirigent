"""Connections: coded credential records of a contributed kind, redacted in every response.

A connection kind's ``config_model`` marks its secret fields with ``SecretStr``, and that single
declaration is what makes the API redact them and the engine encrypt them. Nothing here ever
returns a secret: a write accepts one, an envelope stores it, a read replaces it with the
redaction marker, and no endpoint reveals a stored credential. An update that sends the marker
back keeps the secret it stands for, which reserves the literal marker as a secret value.
"""

import sqlalchemy as sa
from fastapi import APIRouter, HTTPException, Response, status
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.schemas import ConnectionIn, ConnectionOut, ConnectionUpdate, Page
from dirigent_common import HealthReport, JsonMap
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Connection, utcnow
from dirigent_core.secrets import REDACTED, SecretError, redact, secret_fields
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.logging import get_logger
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip
from dirigent_server.security import AdminDep, PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["connections"])

#: What a raised check is allowed to say on a row that every principal can read.
CHECK_FAILED_HINT = "the check raised; the server log has the message"

_logger = get_logger("connections")


def summarise_failure(error: Exception) -> str:
    """Render a raised check for a row that everyone can read: the class, and nothing else.

    A driver's exception message routinely embeds the whole connection string -- host, user,
    often the password -- and ``last_check_detail`` is served to every principal by
    ``/system/info``. The class name still separates "wrong password" from "host
    unreachable"; the message goes to the process log only. An unhealthy report a connection
    kind returns of its own accord is untouched.
    """
    return f"{type(error).__name__}: {CHECK_FAILED_HINT}"


def render(row: Connection, services: EngineServices) -> ConnectionOut:
    """Render a stored connection with its secret fields replaced by the redaction marker."""
    contributed = services.host.connection_kinds.get(row.kind)
    model = contributed.config_model if contributed else None
    fields = secret_fields(model) if model else []
    visible = redact(model, dict(row.config)) if model else dict(row.config)
    # A sealed field is not on the row at all, so the marker is put back: a form must know
    # the credential is set without being told what it is.
    sealed = REDACTED if row.secret_envelope is not None else None
    for name in fields:
        visible.setdefault(name, sealed)
    return ConnectionOut(
        id=row.id,
        code=row.code,
        name=row.name,
        kind=row.kind,
        description=row.description,
        config=visible,
        secret_fields=fields,
        last_check_at=row.last_check_at,
        last_check_healthy=row.last_check_healthy,
        last_check_detail=row.last_check_detail,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def find(session: AsyncSession, code: str) -> Connection:
    """Read one connection by code, or say this instance has no such credential."""
    found = await session.execute(sa.select(Connection).where(Connection.code == code))
    row = found.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no connection coded {code!r}")
    return row


def restore_marked_secrets(row: Connection, config: JsonMap, services: EngineServices) -> JsonMap:
    """Put each stored secret back where an update carries the marker a read showed for it.

    A read returns ``***`` for a secret that is set, so a form that edits what it read and
    sends the whole document back means "keep this one" by the marker: the stored value is
    substituted before the config is validated and sealed again. The marker with nothing
    stored behind it is refused, because nothing distinguishes it from somebody choosing three
    asterisks as a password. That reserves the literal marker: it cannot be stored as a secret.
    """
    contributed = services.host.connection_kinds.get(row.kind)
    if contributed is None:
        return config
    marked = [name for name in secret_fields(contributed.config_model) if config.get(name) == REDACTED]
    if not marked:
        return config
    try:
        stored = services.secrets.open(row.secret_envelope, key_id=row.secret_key_id)
    except SecretError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    empty = sorted(name for name in marked if stored.get(name) is None)
    if empty:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"{', '.join(empty)} came back as {REDACTED!r}, which is what a read shows for a secret "
                f"that is set, not a secret. Send the real value, or leave the field out to keep what is stored."
            ),
        )
    return {**config, **{name: stored[name] for name in marked}}


def seal(services: EngineServices, kind_id: str, config: JsonMap) -> tuple[JsonMap, bytes | None, str | None]:
    """Validate a config against its kind's model and split it into public and sealed halves."""
    contributed = services.host.connection_kinds.get(kind_id)
    if contributed is None:
        known = ", ".join(sorted(services.host.connection_kinds)) or "none are installed"
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"no connection kind {kind_id!r} is installed ({known})",
        )
    try:
        validated = contributed.config_model.model_validate(config)
    except ValidationError as error:
        # include_input=False: the input here is a credential, and pydantic's default error
        # payload echoes the value that failed into the 422 body and whatever logs it.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=error.errors(include_input=False),
        ) from error
    try:
        return services.secrets.encrypt_config(contributed.config_model, validated)
    except SecretError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get(
    "/connections",
    operation_id="listConnections",
    summary="List connections",
    response_model=Page[ConnectionOut],
)
async def list_connections(
    session: SessionDep,
    services: ServicesDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[ConnectionOut]:
    """List every stored credential record, with its secrets redacted."""
    statement = sa.select(Connection).order_by(Connection.code).limit(limit + 1)
    if after is not None:
        statement = statement.where(Connection.code > after)
    rows = await session.execute(statement)
    found = [render(row, services) for row in rows.scalars()]
    items, following = clip(found, limit, lambda row: row.code)
    return Page(items=items, next=following)


@router.post(
    "/connections",
    operation_id="createConnection",
    summary="Create a connection",
    response_model=ConnectionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    payload: ConnectionIn,
    session: SessionDep,
    services: ServicesDep,
    principal: AdminDep,
) -> ConnectionOut:
    """Validate a credential against its kind, seal its secret half, and store it."""
    existing = await session.execute(sa.select(Connection).where(Connection.code == payload.code))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"a connection coded {payload.code!r} exists")
    public, envelope, key_id = seal(services, payload.kind, payload.config)
    row = Connection(
        code=payload.code,
        name=payload.name,
        kind=payload.kind,
        description=payload.description,
        config=public,
        secret_envelope=envelope,
        secret_key_id=key_id,
    )
    session.add(row)
    await session.flush()
    return render(row, services)


@router.get(
    "/connections/{code}",
    operation_id="getConnection",
    summary="Read a connection",
    response_model=ConnectionOut,
)
async def get_connection(
    code: str, session: SessionDep, services: ServicesDep, principal: PrincipalDep
) -> ConnectionOut:
    """Read one credential record, with its secrets redacted."""
    return render(await find(session, code), services)


@router.patch(
    "/connections/{code}",
    operation_id="updateConnection",
    summary="Update a connection",
    response_model=ConnectionOut,
)
async def update_connection(
    code: str,
    payload: ConnectionUpdate,
    session: SessionDep,
    services: ServicesDep,
    principal: AdminDep,
) -> ConnectionOut:
    """Replace a connection's settings; the config is sent whole, not merged field by field.

    A secret field carrying the redaction marker keeps the secret already stored for it.
    """
    row = await find(session, code)
    if payload.changing("name"):
        row.name = payload.name
    if payload.changing("description"):
        row.description = payload.description
    if payload.config is not None:
        config = restore_marked_secrets(row, payload.config, services)
        public, envelope, key_id = seal(services, row.kind, config)
        row.config = public
        row.secret_envelope = envelope
        row.secret_key_id = key_id
    await session.flush()
    return render(row, services)


@router.delete(
    "/connections/{code}",
    operation_id="deleteConnection",
    summary="Delete a connection",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_connection(code: str, session: SessionDep, principal: AdminDep) -> Response:
    """Remove a credential record, refusing one something still delivers or connects through."""
    row = await find(session, code)
    await session.delete(row)
    try:
        await session.flush()
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"connection {code!r} is still referenced; delete what uses it first",
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/connections/{code}/$check",
    operation_id="checkConnection",
    summary="Check a connection against its external system",
    response_model=HealthReport,
)
async def check_connection(
    code: str,
    session: SessionDep,
    services: ServicesDep,
    principal: AdminDep,
) -> HealthReport:
    """Open the credential and ask its kind whether the external system answers.

    The probe runs between two transactions, never inside one: a transaction holds the write
    lock from the moment it opens, and a probe can last a connect timeout. The row is written
    afterwards with one statement, so a connection deleted meanwhile is simply not written.
    """
    row = await find(session, code)
    await session.commit()
    report = await check(row, services)
    await session.execute(
        sa.update(Connection)
        .where(Connection.code == code)
        .values(last_check_at=utcnow(), last_check_healthy=report.healthy, last_check_detail=report.detail)
    )
    return report


async def check(row: Connection, services: EngineServices) -> HealthReport:
    """Run one connection's own health check, turning any raised failure into a report."""
    contributed = services.host.connection_kinds.get(row.kind)
    if contributed is None:
        return HealthReport(healthy=False, detail=f"no connection kind {row.kind!r} is installed")
    try:
        config = services.secrets.decrypt_config(
            contributed.config_model, dict(row.config), row.secret_envelope, key_id=row.secret_key_id
        )
        return await contributed.check(config)
    except Exception as error:
        # The full text goes to the process log; only a bounded summary reaches the row,
        # which /system/info serves to every principal.
        _logger.warning("connection check failed", connection=row.code, kind=row.kind, error=str(error))
        return HealthReport(healthy=False, detail=summarise_failure(error))
