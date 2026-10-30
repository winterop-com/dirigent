"""The source rows: one per source node, reconciled on every apply, and what an operator does to them.

A row's declaration follows the pipeline's current version. Whether it is paused, its token
and what it has counted are the instance's, and survive an apply.
"""

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import SourceState, TriggerKind
from dirigent_client.schemas import SourceChanges, SourceInputOut, SourceOut, SourceTokenOut, ValidationIssue
from dirigent_core import wakeups
from dirigent_core.artifacts import canonical_json, digest_of
from dirigent_core.auth import PREFIX_LENGTH, hash_token, mint_secret
from dirigent_core.config import Settings
from dirigent_core.engine.definition import PipelineDefinition
from dirigent_core.engine.runs import ACTIVE_RUN_STATUSES
from dirigent_core.errors import DomainError
from dirigent_core.logging import get_logger
from dirigent_core.messages import (
    ROUTE_CLAIMED,
    ROUTE_RACED,
    SOURCE_EMPTY_SECRET,
    SOURCE_NOT_SIGNED,
    SOURCE_TAKES_NO_TOKEN,
    UNKNOWN_SOURCE,
)
from dirigent_core.models import Pipeline, Run, Source, SourceInput, SourceRoute, utcnow
from dirigent_core.secrets import SecretBox
from dirigent_core.sources.rules import declared_routes, source_config
from dirigent_plugin.sources import AnySource, HeldSource, PolledSource, ReceivedSource, Route, SourceAuth

_logger = get_logger("sources")

type AnyReceived = ReceivedSource[Any, Any]

#: The field a signing secret is sealed under.
SIGNING_FIELD: Final = "signing_secret"

#: How many hex characters of a signing secret's SHA-256 a listing shows.
FINGERPRINT_LENGTH: Final = 12

type RouteKey = tuple[str, str]
"""A method and a normalised template, which is what two routes collide on."""


class SourceError(DomainError):
    """A source could not be found, or could not be done to what was asked."""


class UnknownSource(SourceError):
    """No source of the pipeline holds the given code."""

    status = 404
    message = UNKNOWN_SOURCE


class TakesNoToken(SourceError):
    """A token was asked of a source whose callers present none."""

    status = 409
    message = SOURCE_TAKES_NO_TOKEN


class NotSigned(SourceError):
    """A signing secret was given to a source whose callers do not sign."""

    status = 409
    message = SOURCE_NOT_SIGNED


class EmptySigningSecret(SourceError):
    """An empty string was offered as a signing secret."""

    status = 422
    message = SOURCE_EMPTY_SECRET


class RouteRaced(SourceError):
    """Another pipeline claimed a route between this apply's plan and its write."""

    status = 409
    message = ROUTE_RACED


def endpoint_path(settings: Settings, template: str) -> str:
    """Spell where a received source is called: the instance's endpoint prefix, then its template."""
    return f"{settings.endpoint_prefix.rstrip('/')}{template}"


def received(kinds: Mapping[str, AnySource], row: Source) -> tuple[AnyReceived, BaseModel] | None:
    """Read a row as a received kind and its config, or None for a kind the server does not take."""
    kind = kinds.get(row.kind)
    if not isinstance(kind, ReceivedSource):
        return None
    try:
        return kind, source_config(kind, row.config)
    except ValidationError:
        return None


def route_of(kinds: Mapping[str, AnySource], row: Source) -> Route | None:
    """Read the route a row answers, or None when it answers none."""
    found = received(kinds, row)
    if found is None:
        return None
    kind, config = found
    return kind.route(config)


async def claimed_route_issues(
    session: AsyncSession, definition: PipelineDefinition, kinds: Mapping[str, AnySource]
) -> list[ValidationIssue]:
    """Refuse a route another pipeline's source already answers, one method at one template."""
    declared = declared_routes(definition, kinds)
    if not declared:
        return []
    rows = await session.execute(
        sa.select(SourceRoute.method, SourceRoute.normalised, Source.code, Pipeline.code)
        .join(Source, Source.id == SourceRoute.source_id)
        .join(Pipeline, Pipeline.id == Source.pipeline_id)
        .where(
            Pipeline.code != definition.code,
            SourceRoute.normalised.in_({normalised for *_, normalised in declared}),
        )
    )
    held: dict[RouteKey, tuple[str, str]] = {
        (method, normalised): (step, pipeline) for method, normalised, step, pipeline in rows
    }
    issues: list[ValidationIssue] = []
    for step, method, template, normalised in declared:
        other = held.get((method, normalised))
        if other is not None:
            issues.append(
                ValidationIssue.of(
                    ROUTE_CLAIMED,
                    location=f"steps.{step}.source.path",
                    method=method,
                    template=template,
                    step=repr(other[0]),
                    pipeline=repr(other[1]),
                )
            )
    return issues


async def reconcile_sources(
    session: AsyncSession,
    settings: Settings,
    kinds: Mapping[str, AnySource],
    secrets: SecretBox,
    pipeline: Pipeline,
    definition: PipelineDefinition,
) -> SourceChanges:
    """Create, redeclare and retire one pipeline's source rows, keeping what the instance did to them.

    Every route that stops being answered is released before any is claimed, so a route moved
    from one source of the pipeline to another is not refused as taken by itself.
    """
    existing = {row.code: row for row in await _rows_of(session, pipeline.id)}
    held = await _routes_of(session, [row.id for row in existing.values()])
    wanted = {name: _wanted_routes(definition, kinds, name) for name in definition.sources}

    removed = sorted(code for code in existing if code not in wanted)
    for code in removed:
        await session.delete(existing[code])
    kept: dict[str, set[RouteKey]] = {}
    for code, row in existing.items():
        keep = wanted.get(code)
        if keep is None:
            continue
        kept[code] = set()
        for route in held.get(row.id, []):
            key = (route.method, route.normalised)
            if keep.get(key) == route.template:
                kept[code].add(key)
            else:
                await session.delete(route)
    await session.flush()

    created: list[str] = []
    updated: list[str] = []
    tokens: list[SourceTokenOut] = []
    for code in definition.sources:
        step = definition.steps[code]
        node = step.source
        assert node is not None  # every name in sources is a source step
        declared = (step.name, step.description, node.kind, node.config)
        row = existing.get(code) or Source(pipeline_id=pipeline.id, code=code)
        if code not in existing:
            session.add(row)
            created.append(code)
        elif (row.name, row.description, row.kind, row.config) != declared:
            updated.append(code)
        row.name, row.description, row.kind, row.config = declared
        _schedule_poll(kinds, row, redeclared=code in created or code in updated)
        await session.flush()
        minted = _mint_if_wanted(kinds, secrets, row)
        if minted is not None:
            tokens.append(_token_out(settings, kinds, pipeline, row, minted))
        await _claim(session, row, wanted[code], kept.get(code, set()))

    for code in [*created, *updated, *removed]:
        await wakeups.publish(session, wakeups.SOURCES, f"{pipeline.code}/{code}")
    changes = SourceChanges(created=created, updated=updated, removed=removed, tokens=tokens)
    if not changes.empty:
        _logger.info("sources reconciled", pipeline=pipeline.code, created=created, updated=updated, removed=removed)
    return changes


def polled(kinds: Mapping[str, AnySource], row: Source) -> tuple[PolledSource[Any, Any], BaseModel] | None:
    """Read a row as a polled kind and its validated config, or None for any other row."""
    kind = kinds.get(row.kind)
    if not isinstance(kind, PolledSource):
        return None
    try:
        return kind, source_config(kind, row.config)
    except ValidationError:
        return None


def held(kinds: Mapping[str, AnySource], row: Source) -> tuple[HeldSource[Any, Any], BaseModel] | None:
    """Read a row as a held kind and its validated config, or None for any other row."""
    kind = kinds.get(row.kind)
    if not isinstance(kind, HeldSource):
        return None
    try:
        return kind, source_config(kind, row.config)
    except ValidationError:
        return None


def worker_hosted(kinds: Mapping[str, AnySource], row: Source) -> bool:
    """Say whether a worker polls or holds this source, rather than the server receiving it."""
    return isinstance(kinds.get(row.kind), PolledSource | HeldSource)


def _schedule_poll(kinds: Mapping[str, AnySource], row: Source, *, redeclared: bool) -> None:
    """Due a worker-hosted source now when it is new or redeclared, and reset a cursor its config no longer owns.

    For a held source the due time is when a worker may take it up, which a failure pushes back.
    """
    if held(kinds, row) is not None:
        if redeclared or row.next_poll_at is None:
            row.next_poll_at = utcnow()
        return
    found = polled(kinds, row)
    if found is None:
        row.next_poll_at = None
        return
    kind, config = found
    key = kind.cursor_key(config)
    owner = None if key is None else digest_of(canonical_json(key))
    if row.cursor_for != owner:
        row.cursor = None
        row.cursor_for = owner
    if redeclared or row.next_poll_at is None:
        row.next_poll_at = utcnow()


def _wanted_routes(definition: PipelineDefinition, kinds: Mapping[str, AnySource], name: str) -> dict[RouteKey, str]:
    """Name the routes one source of a document answers, each with the template it is written as."""
    return {
        (method, normalised): template
        for step, method, template, normalised in declared_routes(definition, kinds)
        if step == name
    }


async def _rows_of(session: AsyncSession, pipeline_id: UUID) -> list[Source]:
    """Read a pipeline's source rows."""
    rows = await session.execute(sa.select(Source).where(Source.pipeline_id == pipeline_id))
    return list(rows.scalars())


async def _routes_of(session: AsyncSession, source_ids: Sequence[UUID]) -> dict[UUID, list[SourceRoute]]:
    """Read the routes each of these sources answers now."""
    if not source_ids:
        return {}
    rows = await session.execute(sa.select(SourceRoute).where(SourceRoute.source_id.in_(source_ids)))
    held: dict[UUID, list[SourceRoute]] = {}
    for route in rows.scalars():
        held.setdefault(route.source_id, []).append(route)
    return held


async def _claim(session: AsyncSession, row: Source, wanted: dict[RouteKey, str], kept: set[RouteKey]) -> None:
    """Claim the routes a source answers that it does not hold yet, refusing one another pipeline took first."""
    missing = [(key, template) for key, template in wanted.items() if key not in kept]
    if not missing:
        return
    try:
        async with session.begin_nested():
            session.add_all(
                SourceRoute(source_id=row.id, method=method, template=template, normalised=normalised)
                for (method, normalised), template in missing
            )
            await session.flush()
    except IntegrityError as error:
        (method, _), template = missing[0]
        raise RouteRaced(method=method, template=template) from error


def auth_of(kinds: Mapping[str, AnySource], row: Source) -> SourceAuth | None:
    """Read how a received source's callers authenticate, or None for a source nobody calls."""
    found = received(kinds, row)
    return found[0].auth(found[1]) if found else None


def _mint_if_wanted(kinds: Mapping[str, AnySource], secrets: SecretBox, row: Source) -> str | None:
    """Give a row the credential its auth takes when it holds none, and drop one it no longer takes."""
    auth = auth_of(kinds, row)
    kind = auth.kind if auth is not None else None
    if kind != "token":
        row.token_hash = None
        row.token_prefix = None
    if kind != "hmac":
        row.signing_secret = None
        row.signing_key_id = None
        row.secret_fingerprint = None
    if kind == "token" and row.token_hash is None:
        return _set_token(row)
    if kind == "hmac" and row.signing_secret is None:
        return _set_signing_secret(row, secrets, mint_secret())
    return None


def _set_token(row: Source) -> str:
    """Give a row a new token, keeping only its hash, and hand the token back once."""
    token = mint_secret()
    row.token_hash = hash_token(token)
    row.token_prefix = token[:PREFIX_LENGTH]
    return token


def _set_signing_secret(row: Source, secrets: SecretBox, secret: str) -> str:
    """Seal a signing secret on a row with the instance key, and hand it back."""
    if not secret:
        raise EmptySigningSecret
    row.signing_secret = secrets.seal({SIGNING_FIELD: secret})
    row.signing_key_id = secrets.key_id
    row.secret_fingerprint = fingerprint_of(secret)
    row.token_prefix = None
    return secret


def fingerprint_of(secret: str) -> str:
    """Name a signing secret by a short hash, which a holder can recompute and which reveals none of it."""
    return hashlib.sha256(secret.encode()).hexdigest()[:FINGERPRINT_LENGTH]


def open_signing_secret(secrets: SecretBox, row: Source) -> bytes | None:
    """Open the signing secret sealed on a row, or None for a row that holds none."""
    if row.signing_secret is None:
        return None
    value = secrets.open(row.signing_secret, key_id=row.signing_key_id).get(SIGNING_FIELD)
    return value.encode() if isinstance(value, str) else None


def _token_out(
    settings: Settings, kinds: Mapping[str, AnySource], pipeline: Pipeline, row: Source, token: str
) -> SourceTokenOut:
    """Render a minted credential with where it is presented, and how."""
    route = route_of(kinds, row)
    auth = auth_of(kinds, row)
    signed = auth is not None and auth.kind == "hmac"
    return SourceTokenOut(
        source_id=row.id,
        pipeline=pipeline.code,
        code=row.code,
        auth="hmac" if signed else "token",
        header=auth.header if signed and auth is not None else None,
        token=token,
        prefix=row.token_prefix,
        fingerprint=row.secret_fingerprint,
        url_path=endpoint_path(settings, route.template if route else "/"),
    )


async def require_source(session: AsyncSession, pipeline: Pipeline, code: str) -> Source:
    """Find one of a pipeline's sources by its step code, or raise :class:`UnknownSource`."""
    found = await session.execute(sa.select(Source).where(Source.pipeline_id == pipeline.id, Source.code == code))
    row = found.scalar_one_or_none()
    if row is None:
        raise UnknownSource(pipeline=repr(pipeline.code), code=repr(code))
    return row


async def list_sources(
    session: AsyncSession, *, pipeline_id: UUID | None = None, after: UUID | None = None, limit: int | None = None
) -> list[tuple[Source, Pipeline]]:
    """Read source rows with their pipelines, in the order they were created."""
    statement = sa.select(Source, Pipeline).join(Pipeline, Pipeline.id == Source.pipeline_id).order_by(Source.id)
    if pipeline_id is not None:
        statement = statement.where(Source.pipeline_id == pipeline_id)
    if after is not None:
        statement = statement.where(Source.id > after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return [(row, pipeline) for row, pipeline in rows]


async def in_flight(session: AsyncSession, source_ids: Sequence[UUID]) -> dict[UUID, int]:
    """Count the unsettled runs each of these sources started."""
    if not source_ids:
        return {}
    rows = await session.execute(
        sa.select(Run.triggered_by_id, sa.func.count())
        .where(
            Run.triggered_by_kind == TriggerKind.SOURCE,
            Run.triggered_by_id.in_(source_ids),
            Run.status.in_(ACTIVE_RUN_STATUSES),
        )
        .group_by(Run.triggered_by_id)
    )
    return {source_id: count for source_id, count in rows if source_id is not None}


def state_of(
    row: Source, *, pipeline_active: bool, unsettled: int, bound: int | None, is_polled: bool = False
) -> SourceState:
    """Read whether a source takes inputs now, from its row and the runs it has unsettled."""
    if row.paused or not pipeline_active:
        return SourceState.DRAINING if unsettled else SourceState.PAUSED
    if is_polled and row.failures > 0:
        return SourceState.FAILING
    if is_polled and row.polled_at is None:
        return SourceState.STARTING
    if bound is not None and unsettled >= bound:
        return SourceState.BACKLOGGED
    return SourceState.LISTENING


def max_in_flight(kinds: Mapping[str, AnySource], row: Source) -> int | None:
    """Read how many unsettled runs a row allows, or None for no bound."""
    kind = kinds.get(row.kind)
    if kind is None:
        return None
    try:
        return kind.max_in_flight(source_config(kind, row.config))
    except ValidationError:
        return None


def source_out(
    settings: Settings, kinds: Mapping[str, AnySource], row: Source, pipeline: Pipeline, unsettled: int
) -> SourceOut:
    """Render a row as a listing shows it."""
    found = received(kinds, row)
    route = found[0].route(found[1]) if found else None
    bound = max_in_flight(kinds, row)
    is_polled = worker_hosted(kinds, row)
    return SourceOut(
        id=row.id,
        pipeline=pipeline.code,
        code=row.code,
        name=row.name,
        description=row.description,
        kind=row.kind,
        state=state_of(row, pipeline_active=pipeline.active, unsettled=unsettled, bound=bound, is_polled=is_polled),
        methods=list(route.methods) if route else [],
        route=route.template if route else None,
        url_path=endpoint_path(settings, route.template) if route else None,
        auth=found[0].auth(found[1]).kind if found else None,
        signature_header=_signature_header(kinds, row),
        token_prefix=row.token_prefix,
        secret_fingerprint=row.secret_fingerprint,
        in_flight=unsettled,
        max_in_flight=bound,
        accepted=row.accepted,
        refused=row.refused,
        last_input_at=row.last_input_at,
        summary=summary_of(kinds, row),
        polled_at=row.polled_at,
        next_poll_at=row.next_poll_at if is_polled else None,
        failures=row.failures,
        last_error=row.last_error,
        created_at=row.created_at,
    )


def _signature_header(kinds: Mapping[str, AnySource], row: Source) -> str | None:
    """Name the header an ``hmac`` source's signature arrives in, or None for any other source."""
    auth = auth_of(kinds, row)
    return auth.header if auth is not None and auth.kind == "hmac" else None


def summary_of(kinds: Mapping[str, AnySource], row: Source) -> str | None:
    """Say in one line what a source listens to, as its kind writes it."""
    kind = kinds.get(row.kind)
    if kind is None:
        return None
    try:
        return kind.summary_of(source_config(kind, row.config))
    except ValidationError:
        return None


async def set_paused(session: AsyncSession, pipeline: Pipeline, row: Source, *, paused: bool) -> Source:
    """Pause or resume a source, keeping its token and its counts."""
    row.paused = paused
    if not paused and row.next_poll_at is not None:
        row.next_poll_at = utcnow()
    await session.flush()
    await wakeups.publish(session, wakeups.SOURCES, f"{pipeline.code}/{row.code}")
    _logger.info("source paused" if paused else "source resumed", pipeline=pipeline.code, source=row.code)
    return row


async def rotate_source_token(
    session: AsyncSession,
    settings: Settings,
    kinds: Mapping[str, AnySource],
    secrets: SecretBox,
    pipeline: Pipeline,
    row: Source,
) -> SourceTokenOut:
    """Mint a new token or signing secret for a source and forget the old one, immediately."""
    auth = auth_of(kinds, row)
    kind = auth.kind if auth is not None else None
    if kind not in {"token", "hmac"}:
        raise TakesNoToken(code=repr(row.code), pipeline=repr(pipeline.code), auth=kind or "not received")
    token = _set_token(row) if kind == "token" else _set_signing_secret(row, secrets, mint_secret())
    await session.flush()
    await wakeups.publish(session, wakeups.SOURCES, f"{pipeline.code}/{row.code}")
    _logger.info("source token rotated", pipeline=pipeline.code, source=row.code)
    return _token_out(settings, kinds, pipeline, row, token)


async def set_signing_secret(
    session: AsyncSession,
    kinds: Mapping[str, AnySource],
    secrets: SecretBox,
    pipeline: Pipeline,
    row: Source,
    secret: str,
) -> Source:
    """Replace an ``hmac`` source's signing secret with one a sender issued, such as a provider's own."""
    auth = auth_of(kinds, row)
    kind = auth.kind if auth is not None else None
    if kind != "hmac":
        raise NotSigned(code=repr(row.code), pipeline=repr(pipeline.code), auth=kind or "not received")
    _set_signing_secret(row, secrets, secret)
    await session.flush()
    await wakeups.publish(session, wakeups.SOURCES, f"{pipeline.code}/{row.code}")
    _logger.info("source signing secret set", pipeline=pipeline.code, source=row.code)
    return row


async def list_inputs(
    session: AsyncSession, source_id: UUID, *, after: int | None = None, limit: int | None = None
) -> list[SourceInput]:
    """Read a source's recent inputs, newest first, refusals included."""
    statement = sa.select(SourceInput).where(SourceInput.source_id == source_id).order_by(SourceInput.id.desc())
    if after is not None:
        statement = statement.where(SourceInput.id < after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


def input_out(row: SourceInput) -> SourceInputOut:
    """Render one journal row."""
    return SourceInputOut(
        id=row.id,
        created_at=row.created_at,
        outcome=row.outcome,
        status=row.status,
        run_id=row.run_id,
        code=row.code,
        reason=row.reason,
        params=row.params,
        method=row.method,
        path=row.path,
        label=row.label,
        body_bytes=row.body_bytes,
        duration_ms=row.duration_ms,
        caller=row.caller,
    )
