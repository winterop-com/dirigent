"""The endpoint intake: a call to a received source, checked in one order, becomes a run or a refusal.

Each check answers for itself, in this order: the instance's bucket for the method and path,
the route (404, 405), the token (401), or for a signed source the capped read (413) and the
signature with its timestamp (401), then the source's own bucket (429), the source and its
pipeline taking input (503), the content type (415), the capped read (413), the parse (400),
the runs in flight (503), then the run. Nothing before the source's own bucket writes a
journal row or spends from it, so a caller without the token or the secret, or in a loop,
causes no writes; those are counted in telemetry instead. The one write ahead of the bucket is
the record of a signature taken, which only a caller holding the secret causes.
"""

import hmac
import math
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from jsonschema import FormatChecker
from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import InputOutcome, TriggerKind
from dirigent_client.schemas import InputAccepted
from dirigent_common import JsonMap
from dirigent_common.durations import format_duration
from dirigent_core import telemetry, wakeups
from dirigent_core.auth import hash_token
from dirigent_core.engine.definition import load_definition
from dirigent_core.engine.runs import Attribution, Entry, create_run
from dirigent_core.engine.services import EngineServices
from dirigent_core.engine.state import lock_pipeline
from dirigent_core.errors import DomainError
from dirigent_core.logging import get_logger
from dirigent_core.messages import (
    INTAKE_RATE,
    METHOD_NOT_ANSWERED,
    NO_ROUTE,
    SOURCE_BACKLOGGED,
    SOURCE_BODY_TOO_LARGE,
    SOURCE_KIND_MISSING,
    SOURCE_PAUSED,
    SOURCE_PIPELINE_INACTIVE,
    SOURCE_RATE,
    SOURCE_RUN_REFUSED,
    SOURCE_RUN_SKIPPED,
    SOURCE_SIGNATURE_MISMATCH,
    SOURCE_SIGNATURE_REPLAYED,
    SOURCE_SIGNATURE_REQUIRED,
    SOURCE_SIGNATURE_TIMESTAMP,
    SOURCE_WAITING_FULL,
    SOURCE_WAITING_SHARE,
    TOKEN_REFUSED,
)
from dirigent_core.models import (
    Pipeline,
    PipelineVersion,
    Source,
    SourceInput,
    SourceRoute,
    SourceSignature,
    utcnow,
)
from dirigent_core.ratelimit import TokenBucket
from dirigent_core.sources.rows import AnyReceived, endpoint_path, in_flight, open_signing_secret, received
from dirigent_core.sources.rules import source_config
from dirigent_core.sources.waiter import Hold, Seating, Waiter
from dirigent_plugin.blocks import Logger
from dirigent_plugin.sources import (
    SIGNATURE_TIMESTAMP_HEADER,
    Ignore,
    InboundRequest,
    Refusal,
    Route,
    SourceAuth,
    sign_body,
)

#: How long a process answers from the routes it read before reading them again, a notification or not.
ROUTES_TTL_SECONDS: Final = 5.0

#: The scheme an endpoint's token is presented under.
BEARER: Final = "bearer"

_logger = get_logger("intake")

type ReadBody = Callable[[int], Awaitable[bytes]]
"""Read a request's body, stopping one byte past the limit it is given."""


class Accepted(BaseModel):
    """An input that became a run, and the hold its caller is kept on when a reply may answer it."""

    model_config = ConfigDict(frozen=True)

    accepted: InputAccepted
    input_id: int
    """The journal row, which the caller's answer settles once it is held."""

    hold: Hold | None = None


type Taken = Accepted | Refusal | Ignore


class Listening(BaseModel):
    """One template a source answers, and the methods it answers there."""

    model_config = ConfigDict(frozen=True)

    source_id: UUID
    route: Route


class Matched(BaseModel):
    """The source a call reached, and what its template took from the path."""

    model_config = ConfigDict(frozen=True)

    source_id: UUID
    route: Route
    path_params: dict[str, str]


class RouteTable(BaseModel):
    """Every route this instance's received sources answer, as one process last read them."""

    model_config = ConfigDict(frozen=True)

    listening: list[Listening] = Field(default_factory=list[Listening])

    def find(self, method: str, path: str) -> Matched | list[str] | None:
        """Find the source a call reaches, the methods its path answers when the method is not one, or nothing.

        The template with the most literal segments wins, so ``/customers/new`` is matched before
        ``/customers/{id}``.
        """
        matches = [(entry, taken) for entry in self.listening if (taken := entry.route.match(path)) is not None]
        matches.sort(key=lambda match: match[0].route.literal_segments, reverse=True)
        for entry, taken in matches:
            if method in entry.route.methods:
                return Matched(source_id=entry.source_id, route=entry.route, path_params=taken)
        if matches:
            return sorted({allowed for entry, _ in matches for allowed in entry.route.methods})
        return None


async def read_routes(session: AsyncSession) -> RouteTable:
    """Read every route the instance's sources answer, each template with its methods."""
    rows = await session.execute(sa.select(SourceRoute.source_id, SourceRoute.template, SourceRoute.method))
    grouped: dict[tuple[UUID, str], list[str]] = {}
    for source_id, template, method in rows:
        grouped.setdefault((source_id, template), []).append(method)
    return RouteTable(
        listening=[
            Listening(source_id=source_id, route=Route(methods=tuple(sorted(methods)), template=template))
            for (source_id, template), methods in grouped.items()
        ]
    )


class Call(BaseModel):
    """One call as it arrived, before its body is read."""

    model_config = ConfigDict(frozen=True)

    method: str
    path: str
    query: list[tuple[str, str]]
    headers: dict[str, str]
    """Every header, lowercased."""

    caller: str | None = None


class Intake:
    """What one server process answers under the endpoint prefix: its routes and its buckets.

    The routes are read again once a source changes anywhere, which ``dirigent_sources`` says,
    or once they are older than :data:`ROUTES_TTL_SECONDS`, since a notification is a hint.
    The buckets are this process's own, so behind N replicas a caller is allowed N times the rate.
    """

    def __init__(self) -> None:
        """Start with no routes read and empty buckets."""
        self.instance_bucket = TokenBucket()
        self.source_bucket = TokenBucket()
        self._table: RouteTable | None = None
        self._mark: wakeups.Mark | None = None
        self._read_at = 0.0

    async def routes(self, session: AsyncSession) -> RouteTable:
        """Answer from the routes last read, reading them again when they may be stale."""
        moment = time.monotonic()
        table, mark = self._table, self._mark
        if table is None or mark is None or wakeups.hub.moved(mark) or moment - self._read_at > ROUTES_TTL_SECONDS:
            self._mark = wakeups.hub.mark(wakeups.SOURCES)
            self._table = table = await read_routes(session)
            self._read_at = moment
        return table

    async def take(
        self,
        session: AsyncSession,
        services: EngineServices,
        call: Call,
        read: ReadBody,
        waiter: Waiter | None = None,
    ) -> Taken:
        """Answer one call: a run accepted, a refusal with the status it is answered with, or a sign of life.

        With a waiter, an input that can reach a reply takes one of its seats, which the caller
        of this method gives back once it has waited on the hold.
        """
        started = time.monotonic()
        received_at = utcnow()
        settings = services.settings
        limit = settings.source_intake_rate_per_minute
        if not self.instance_bucket.allow(f"{call.method} {call.path}", per_minute=limit):
            return _counted(Refusal.of(INTAKE_RATE, status=429, headers=_retry_after(limit), per_minute=limit))
        found = (await self.routes(session)).find(call.method, call.path)
        called = endpoint_path(settings, call.path)
        if found is None:
            return _counted(Refusal.of(NO_ROUTE, status=404, method=call.method, path=called))
        if isinstance(found, list):
            allowed = ", ".join(found)
            return _counted(
                Refusal.of(
                    METHOD_NOT_ANSWERED,
                    status=405,
                    headers={"Allow": allowed},
                    path=called,
                    allowed=allowed,
                    method=call.method,
                )
            )
        row = await session.get(Source, found.source_id)
        pipeline = await session.get(Pipeline, row.pipeline_id) if row is not None else None
        if row is None or pipeline is None:
            return _counted(Refusal.of(NO_ROUTE, status=404, method=call.method, path=called))
        kind = received(services.sources, row)
        if kind is None:
            return _counted(Refusal.of(SOURCE_KIND_MISSING, status=503, code=repr(row.code), kind=repr(row.kind)))
        source, config = kind
        auth = source.auth(config)
        if auth.kind == "token" and not _presents(row, call.headers):
            return _counted(
                Refusal.of(TOKEN_REFUSED, status=401, headers={"WWW-Authenticate": 'Bearer realm="dirigent"'})
            )
        cap = settings.source_max_body
        declared = source.max_body(config)
        most = min(declared, cap) if declared is not None else cap
        body: bytes | None = None
        if auth.kind == "hmac":
            body = await read(most)
            if len(body) > most:
                return _counted(Refusal.of(SOURCE_BODY_TOO_LARGE, status=413, limit=most))
            unsigned = await _unsigned(session, services, row, auth, call.headers, body, received_at)
            if unsigned is not None:
                return _counted(unsigned)
        rate = source.rate(config)
        if rate is not None and not self.source_bucket.allow(
            str(row.id), per_minute=rate.per_minute, capacity=rate.burst
        ):
            return _counted(
                Refusal.of(SOURCE_RATE, status=429, headers=_retry_after(rate.per_minute), per_minute=rate.per_minute)
            )
        journal = _Journal(session, row, call, started)
        if not pipeline.active:
            return await journal.refuse(
                Refusal.of(SOURCE_PIPELINE_INACTIVE, status=503, pipeline=repr(pipeline.code), code=repr(row.code))
            )
        if row.paused:
            return await journal.refuse(
                Refusal.of(SOURCE_PAUSED, status=503, pipeline=repr(pipeline.code), code=repr(row.code))
            )
        head = InboundRequest(
            method=call.method,
            path=call.path,
            route=found.route.template,
            path_params=found.path_params,
            query=call.query,
            headers=call.headers,
            received_at=received_at,
        )
        refused = source.admit(config, head)
        if refused is not None:
            return await journal.refuse(refused)
        if body is None:
            body = await read(most)
        journal.body_bytes = len(body)
        if len(body) > most:
            return await journal.refuse(Refusal.of(SOURCE_BODY_TOO_LARGE, status=413, limit=most))
        made = await source.receive(config, head.model_copy(update={"body": body}), _ReceiveContext(services=services))
        if isinstance(made, Ignore):
            telemetry.record_input("ignored", 204)
            return made
        if isinstance(made, Refusal):
            return await journal.refuse(made)
        return await _enter(
            session, services, journal, source, pipeline, row, made.model_dump(mode="json"), call, waiter
        )


async def _enter(
    session: AsyncSession,
    services: EngineServices,
    journal: "_Journal",
    source: AnyReceived,
    pipeline: Pipeline,
    row: Source,
    output: JsonMap,
    call: Call,
    waiter: Waiter | None,
) -> Taken:
    """Bound the runs in flight and the callers held, then create the run the input enters."""
    bound = source.max_in_flight(source_config(source, row.config))
    if bound is not None:
        # Run creation takes this lock too, so two calls cannot both count one slot free.
        await lock_pipeline(session, pipeline.id)
        unsettled = (await in_flight(session, [row.id])).get(row.id, 0)
        if unsettled >= bound:
            return await journal.refuse(
                Refusal.of(SOURCE_BACKLOGGED, status=503, code=repr(row.code), in_flight=unsettled)
            )
    found = await session.execute(
        sa.select(PipelineVersion).where(
            PipelineVersion.pipeline_id == pipeline.id, PipelineVersion.version == pipeline.current_version
        )
    )
    version = found.scalar_one()
    timeout, replies, path = _reply_reach(services, version, row.code)
    held = waiter is not None and bool(replies)
    if held and waiter is not None:
        seating = waiter.reserve(row.id)
        if seating is Seating.SERVER_FULL:
            return await journal.refuse(Refusal.of(SOURCE_WAITING_FULL, status=503, waiting=waiter.seats))
        if seating is Seating.SOURCE_FULL:
            return await journal.refuse(
                Refusal.of(SOURCE_WAITING_SHARE, status=503, code=repr(row.code), waiting=waiter.held_by[row.id])
            )
    try:
        taken = await _create(session, services, journal, pipeline, row, version, output, call)
    except BaseException:
        if held and waiter is not None:
            waiter.release(row.id)
        raise
    if not isinstance(taken, Accepted) or not held:
        if held and waiter is not None:
            waiter.release(row.id)
        return taken
    hold = Hold(
        run_id=taken.accepted.run_id, source_id=row.id, replies=tuple(replies), path=tuple(path), timeout=timeout
    )
    return taken.model_copy(update={"hold": hold})


def _reply_reach(services: EngineServices, version: PipelineVersion, source: str) -> tuple[float, list[str], list[str]]:
    """Name the replies an input at a source can reach, the steps leading to them, and how long it is held."""
    definition = load_definition(version.document)
    replies = definition.replies_reached_from(source)
    if not replies:
        return 0.0, [], []
    reach = set(definition.descendants_of(source))
    leading = {step for reply in replies for step in definition.ancestors_of(reply) if step in reach}
    path = [name for name in definition.steps if name in leading or name in replies]
    longest = max(node.timeout for reply in replies if (node := definition.steps[reply].reply) is not None)
    return min(longest, services.settings.source_reply_max).total_seconds(), replies, path


async def _create(
    session: AsyncSession,
    services: EngineServices,
    journal: "_Journal",
    pipeline: Pipeline,
    row: Source,
    version: PipelineVersion,
    output: JsonMap,
    call: Call,
) -> Taken:
    """Create the run an input enters, and journal it as accepted or refused."""
    entry = Entry(
        step=row.code,
        output=output,
        via="request",
        note=f"received {call.method} {call.path} {journal.body_bytes} bytes",
    )
    try:
        async with session.begin_nested():
            run = await create_run(
                session,
                services,
                version,
                attribution=Attribution(kind=TriggerKind.SOURCE, id=row.id, label=f"source {row.code}"),
                entry=entry,
            )
    except DomainError as error:
        return await journal.refuse(Refusal.of(SOURCE_RUN_REFUSED, status=error.status, detail=str(error)))
    if run is None:
        return await journal.refuse(Refusal.of(SOURCE_RUN_SKIPPED, status=409, pipeline=repr(pipeline.code)))
    accepted = InputAccepted(
        run_id=run.id, status=run.status.value, run_url=f"{services.settings.api_prefix}/runs/{run.id}"
    )
    return Accepted(accepted=accepted, input_id=await journal.accept(accepted))


class _Journal:
    """Write what came of one input that reached a source, and count it on the row."""

    def __init__(self, session: AsyncSession, row: Source, call: Call, started: float) -> None:
        """Hold what every journal row of this call carries."""
        self.session = session
        self.row = row
        self.call = call
        self.started = started
        self.body_bytes = 0

    async def refuse(self, refusal: Refusal) -> Refusal:
        """Record a refusal, and hand it back to be answered."""
        await self._write(InputOutcome.REFUSED, refusal.status, refusal=refusal)
        _logger.info("input refused", source=self.row.code, status=refusal.status, code=refusal.code)
        return refusal

    async def accept(self, accepted: InputAccepted) -> int:
        """Record an input that became a run, and hand back its journal row."""
        written = await self._write(InputOutcome.ACCEPTED, 202, run_id=accepted.run_id)
        _logger.info("input accepted", source=self.row.code, run_id=str(accepted.run_id))
        return written

    async def _write(
        self, outcome: InputOutcome, status: int, *, refusal: Refusal | None = None, run_id: UUID | None = None
    ) -> int:
        """Append the journal row and move the row's counts in one statement, so no count is lost."""
        moment = utcnow()
        journal = SourceInput(
            source_id=self.row.id,
            run_id=run_id,
            created_at=moment,
            outcome=outcome,
            status=status,
            code=refusal.code if refusal else None,
            reason=refusal.message if refusal else None,
            params=refusal.params if refusal else None,
            method=self.call.method,
            path=self.call.path,
            body_bytes=self.body_bytes,
            duration_ms=round((time.monotonic() - self.started) * 1000),
            caller=self.call.caller,
        )
        self.session.add(journal)
        await self.session.flush()
        counted = Source.accepted if outcome is InputOutcome.ACCEPTED else Source.refused
        await self.session.execute(
            sa.update(Source)
            .where(Source.id == self.row.id)
            .values({counted: counted + 1, Source.last_input_at: moment})
            .execution_options(synchronize_session=False)
        )
        telemetry.record_input(outcome.value, status)
        return journal.id


async def settle_input(
    session: AsyncSession, input_id: int, outcome: InputOutcome, status: int, started: float
) -> None:
    """Write what a held caller was answered with onto its journal row, and how long it was held."""
    await session.execute(
        sa.update(SourceInput)
        .where(SourceInput.id == input_id)
        .values(outcome=outcome, status=status, duration_ms=round((time.monotonic() - started) * 1000))
        .execution_options(synchronize_session=False)
    )
    telemetry.record_input(outcome.value, status)


class _ReceiveContext(BaseModel):
    """What a received kind may reach while it turns a request into an input."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    services: EngineServices

    @property
    def log(self) -> Logger:
        """Where the kind says what it did with the request."""
        return _ProcessLog()

    @property
    def format_checker(self) -> FormatChecker:
        """The instance's assembled format checker."""
        return self.services.format_checker


class _ProcessLog:
    """A received kind's log, written to the server's own: no run exists yet to hold it."""

    def debug(self, message: str, **fields: JsonValue) -> None:
        """Record a debug-level entry."""
        _logger.debug(message, **fields)

    def info(self, message: str, **fields: JsonValue) -> None:
        """Record an info-level entry."""
        _logger.info(message, **fields)

    def warning(self, message: str, **fields: JsonValue) -> None:
        """Record a warning-level entry."""
        _logger.warning(message, **fields)

    def error(self, message: str, **fields: JsonValue) -> None:
        """Record an error-level entry."""
        _logger.error(message, **fields)


def _counted(refusal: Refusal) -> Refusal:
    """Count a refusal no journal row records, and hand it back to be answered."""
    telemetry.record_input(InputOutcome.REFUSED.value, refusal.status)
    return refusal


def _presents(row: Source, headers: Mapping[str, str]) -> bool:
    """Say whether a call presents this source's token as a bearer credential."""
    if row.token_hash is None:
        return False
    scheme, _, credential = headers.get("authorization", "").partition(" ")
    if scheme.lower() != BEARER or not credential.strip():
        return False
    return hmac.compare_digest(hash_token(credential.strip()), row.token_hash)


async def _unsigned(
    session: AsyncSession,
    services: EngineServices,
    row: Source,
    auth: SourceAuth,
    headers: Mapping[str, str],
    body: bytes,
    moment: datetime,
) -> Refusal | None:
    """Refuse a call whose signature is missing, stale, not this source's secret's, or taken before.

    The signature covers ``<timestamp>.<body>`` and the timestamp has to be within the
    instance's window of now. A signature taken is recorded until its timestamp leaves the
    window, so the same call sent again is refused for one reason or the other. Both sides of
    the comparison are bytes, since the header is the caller's and one character outside ASCII
    would otherwise raise rather than refuse.
    """
    presented = headers.get(auth.header.lower())
    if not presented:
        return Refusal.of(SOURCE_SIGNATURE_REQUIRED, status=401, header=auth.header)
    window = services.settings.source_signature_window
    stamp = headers.get(SIGNATURE_TIMESTAMP_HEADER.lower(), "").strip()
    signed_at = _signed_at(stamp)
    if signed_at is None or abs(moment - signed_at) > window:
        return Refusal.of(
            SOURCE_SIGNATURE_TIMESTAMP, status=401, header=SIGNATURE_TIMESTAMP_HEADER, window=format_duration(window)
        )
    secret = open_signing_secret(services.secrets, row)
    offered = presented.strip().removeprefix("sha256=")
    expected = sign_body(secret or b"", stamp, body)
    if secret is None or not hmac.compare_digest(expected.encode("ascii"), offered.encode("utf-8", "surrogateescape")):
        return Refusal.of(SOURCE_SIGNATURE_MISMATCH, status=401)
    await session.execute(
        sa.delete(SourceSignature)
        .where(SourceSignature.source_id == row.id, SourceSignature.signed_at < moment - window)
        .execution_options(synchronize_session=False)
    )
    try:
        async with session.begin_nested():
            session.add(SourceSignature(source_id=row.id, signature=expected, signed_at=signed_at))
    except IntegrityError:
        return Refusal.of(SOURCE_SIGNATURE_REPLAYED, status=401)
    return None


def _signed_at(stamp: str) -> datetime | None:
    """Read a signature's timestamp, whole Unix seconds, or nothing when it is not one."""
    if not stamp.isascii() or not stamp.isdigit() or len(stamp) > 12:
        return None
    return datetime.fromtimestamp(int(stamp), UTC)


def _retry_after(per_minute: int) -> dict[str, str]:
    """Say how long until a bucket refilled at this rate holds one call again."""
    return {"Retry-After": str(max(1, math.ceil(60 / per_minute)))}


def lowered(headers: Iterable[tuple[str, str]]) -> dict[str, str]:
    """Lowercase header names, joining a repeated one with a comma the way HTTP reads it."""
    joined: dict[str, str] = {}
    for name, value in headers:
        key = name.lower()
        joined[key] = f"{joined[key]}, {value}" if key in joined else value
    return joined


__all__ = [
    "Accepted",
    "Call",
    "Ignore",
    "Intake",
    "Refusal",
    "RouteTable",
    "Taken",
    "lowered",
    "read_routes",
    "settle_input",
]
