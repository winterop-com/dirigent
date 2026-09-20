"""Inbound webhooks: mint a token, verify a delivery, map a payload, enqueue a run.

``POST /hooks/{token}`` is the one unauthenticated write surface dirigent exposes. The token
is the whole credential, an HMAC signature is computed over the raw body as it arrived, and
mapped parameters are validated against the pipeline's own schema like any other run's.
"""

import hashlib
import hmac
import json
import secrets as secrets_module
from collections.abc import Mapping
from typing import Any, Final, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import RunPriority, TriggerKind, WebhookOutcome
from dirigent_common import EntityName, Issue, JsonMap, Message
from dirigent_core.engine.definition import ParameterError, PipelineDefinition, WebhookSpec, load_definition
from dirigent_core.engine.runs import Attribution, RunCreationError, create_run
from dirigent_core.engine.services import EngineServices
from dirigent_core.errors import DomainError
from dirigent_core.logging import get_logger
from dirigent_core.messages import (
    BODY_NOT_JSON,
    BODY_NOT_OBJECT,
    BODY_TOO_LARGE,
    DUPLICATE_WEBHOOK,
    EMPTY_SIGNING_SECRET,
    MAPPING_REFUSED,
    NAME_UNDECLARED,
    NO_SECRET_KEY,
    PATH_ADDRESSES_NOTHING,
    PATH_BAD_ROOT,
    PATH_EMPTY,
    PATH_EMPTY_SEGMENT,
    PATH_NOT_ROOTED,
    PAYLOAD_MISSING,
    REQUIRED_UNMAPPED,
    SIGNATURE_MISMATCH,
    SIGNATURE_REQUIRED,
    UNKNOWN_WEBHOOK,
    WEBHOOK_DISABLED,
    WEBHOOK_PARAMS_REFUSED,
    WEBHOOK_PIPELINE_GONE,
    WEBHOOK_PIPELINE_INACTIVE,
    WEBHOOK_PIPELINE_NO_VERSIONS,
    WEBHOOK_PIPELINE_UNREADABLE,
    WEBHOOK_RUN_REFUSED,
)
from dirigent_core.messages import (
    UNKNOWN_TOKEN as UNKNOWN_TOKEN_MESSAGE,
)
from dirigent_core.models import Pipeline, PipelineVersion, Run, WebhookDelivery, WebhookTrigger, utcnow
from dirigent_core.secrets import SecretBox

SIGNATURE_HEADER: Final = "X-Dirigent-Signature"

TOKEN_BYTES: Final = 32

#: How much of a token is stored in the clear beside its hash.
PREFIX_LENGTH: Final = 8

#: How much of a delivery's body is kept as evidence.
PAYLOAD_KEEP_BYTES: Final = 8192

PATH_ROOT: Final = "$."

#: Told for a token that does not resolve and for one that resolves to a disabled webhook:
#: the same thing either way, so the endpoint is not a probing oracle.
UNKNOWN_TOKEN: Final = UNKNOWN_TOKEN_MESSAGE.render()

_logger = get_logger("webhook")


class WebhookError(DomainError):
    """A webhook could not be declared, found, or delivered to."""


class DeliveryRefused(WebhookError):
    """One inbound delivery was refused: what to record, and what the caller may be told.

    Those are not always the same thing: a disabled webhook is recorded honestly in the
    delivery history, but the caller is told only what an unknown token is told.
    """

    def __init__(self, message: Message, /, *, status: int = 400, public: str | None = None, **params: Any) -> None:
        """Carry the recorded reason, the status to answer with, and what the caller sees."""
        super().__init__(message, **params)
        self.reason = str(self)
        self.status = status
        self.public = public if public is not None else self.reason


class DuplicateWebhook(WebhookError):
    """A pipeline already has a webhook of that code."""

    status = 409
    message = DUPLICATE_WEBHOOK


class UnknownWebhook(WebhookError):
    """No webhook of that code exists on this pipeline."""

    status = 404
    message = UNKNOWN_WEBHOOK

    def __init__(self, pipeline: str, code: str) -> None:
        """Name the pipeline and the webhook."""
        super().__init__(pipeline=repr(pipeline), code=repr(code))


class WebhookRequest(BaseModel):
    """What it takes to declare a webhook, from a document, the API, or the CLI."""

    model_config = ConfigDict(frozen=True)

    code: EntityName
    name: str | None = None
    description: str | None = None
    params_from_payload: dict[str, str] = Field(default_factory=dict[str, str])
    hmac_secret: SecretStr | None = Field(default=None, min_length=1)
    """The signing secret, or ``None`` for an unsigned webhook; an empty string is neither."""

    rate_limit_per_minute: int = Field(default=60, ge=1)
    priority: RunPriority | None = None
    """The priority every accepted delivery's run carries, or None to take the pipeline's own."""

    @classmethod
    def from_spec(cls, spec: WebhookSpec) -> "WebhookRequest":
        """Read a document's webhook declaration as a request.

        A document never carries the token or the HMAC secret; both stay in the instance.
        """
        return cls(
            code=spec.code,
            name=spec.name,
            description=spec.description,
            params_from_payload=dict(spec.params_from_payload),
            priority=spec.priority,
        )


class MintedToken(BaseModel):
    """A webhook and the secret it was just given, which is shown exactly once."""

    model_config = ConfigDict(frozen=True)

    webhook_id: UUID
    code: str
    token: SecretStr
    prefix: str


def mint_token() -> str:
    """Mint an unguessable webhook token; the URL path is the whole credential."""
    return secrets_module.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Hash a token the one way the column stores it."""
    return hashlib.sha256(token.encode()).hexdigest()


def sign(secret: bytes, body: bytes) -> str:
    """Compute the signature a caller is expected to present over the raw request body."""
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify_signature(secret: bytes, body: bytes, presented: str | None) -> None:
    """Check a delivery's signature in constant time, refusing a missing or wrong one.

    An ``sha256=`` prefix is tolerated because several popular senders write one.

    Both sides are compared as bytes: ``hmac.compare_digest`` raises ``TypeError`` on a
    ``str`` holding a character outside ASCII, and the header is attacker-controlled, so
    comparing strings would turn one non-ASCII byte into a 500 and no delivery row.
    """
    if not presented:
        raise DeliveryRefused(SIGNATURE_REQUIRED, status=401, header=SIGNATURE_HEADER)
    offered = presented.split("=", 1)[1] if presented.startswith("sha256=") else presented
    expected = sign(secret, body).encode("ascii")
    if not hmac.compare_digest(expected, offered.strip().encode("utf-8", "surrogateescape")):
        raise DeliveryRefused(SIGNATURE_MISMATCH, status=401)


def read_path(payload: JsonMap, path: str) -> JsonValue:
    """Read one dotted path out of a JSON body, or say precisely where it stopped.

    The syntax is a leading ``$.`` and dotted keys, with a numeric segment addressing a list
    element; there are no filters, wildcards, or slices.
    """
    trimmed = path[len(PATH_ROOT) :] if path.startswith(PATH_ROOT) else path.removeprefix("$")
    parts = [part for part in trimmed.split(".") if part]
    if not parts:
        raise DeliveryRefused(PATH_ADDRESSES_NOTHING, path=repr(path))
    current: JsonValue = payload
    walked = "$"
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            available = (
                ", ".join(sorted(cast("dict[str, Any]", current))) if isinstance(current, dict) else "not an object"
            )
            raise DeliveryRefused(PAYLOAD_MISSING, walked=walked, part=part, available=available)
        walked = f"{walked}.{part}"
    return current


def map_payload(mapping: Mapping[str, str], payload: JsonMap) -> JsonMap:
    """Turn an inbound body into run parameters, one declared path at a time."""
    return {name: read_path(payload, path) for name, path in mapping.items()}


def check_webhook_mapping(definition: PipelineDefinition, mapping: Mapping[str, str]) -> None:
    """Refuse a payload mapping no delivery could ever satisfy, reporting every problem at once.

    Three things are decided here and nowhere else: that each path parses, that each mapped
    name is a parameter the pipeline declares, and that every required parameter without a
    default is mapped. The mapped *values* are not checked, because they only exist once a
    delivery arrives, and they are validated then.
    """
    problems = [*_path_problems(mapping), *_name_problems(definition, mapping)]
    if problems:
        raise WebhookError(MAPPING_REFUSED, problems=problems, detail="; ".join(issue.message for issue in problems))


def _path_problems(mapping: Mapping[str, str]) -> list[Issue]:
    """Parse each declared path against the mapping grammar: ``$`` then dotted, non-empty segments."""
    problems: list[Issue] = []
    for path in mapping.values():
        if not path.startswith("$"):
            problems.append(Issue.of(PATH_NOT_ROOTED, path=repr(path)))
            continue
        rest = path[1:]
        if not rest:
            problems.append(Issue.of(PATH_EMPTY, path=repr(path)))
        elif not rest.startswith("."):
            problems.append(Issue.of(PATH_BAD_ROOT, path=repr(path), found=repr(rest[0])))
        elif any(not segment for segment in rest[1:].split(".")):
            problems.append(Issue.of(PATH_EMPTY_SEGMENT, path=repr(path)))
    return problems


def _name_problems(definition: PipelineDefinition, mapping: Mapping[str, str]) -> list[Issue]:
    """Check the mapped names against the pipeline's parameter schema, both ways.

    A schema declaring no properties and forbidding no additional ones takes any name, so
    there is nothing for a mapped name to be checked against.
    """
    properties = definition.params.get("properties")
    declared = cast("dict[str, Any]", properties) if isinstance(properties, dict) else {}
    problems: list[Issue] = []
    if declared or definition.params.get("additionalProperties") is False:
        named = ", ".join(sorted(declared)) or "none"
        problems = [
            Issue.of(NAME_UNDECLARED, name=repr(name), declared=named) for name in mapping if name not in declared
        ]
    declaration = definition.params.get("required")
    listed = cast("list[object]", declaration) if isinstance(declaration, list) else []
    required = [name for name in listed if isinstance(name, str)]
    for name in required:
        entry = declared.get(name)
        has_default = isinstance(entry, dict) and "default" in cast("dict[str, Any]", entry)
        if name not in mapping and not has_default:
            problems.append(Issue.of(REQUIRED_UNMAPPED, name=repr(name)))
    return problems


async def find_webhook(session: AsyncSession, pipeline_id: UUID, code: str) -> WebhookTrigger | None:
    """Find one webhook by code within its pipeline."""
    found = await session.execute(
        sa.select(WebhookTrigger).where(WebhookTrigger.pipeline_id == pipeline_id, WebhookTrigger.code == code)
    )
    return found.scalar_one_or_none()


async def list_webhooks(
    session: AsyncSession,
    pipeline_id: UUID | None = None,
    *,
    after: str | None = None,
    limit: int | None = None,
) -> list[WebhookTrigger]:
    """List webhooks in code order, for one pipeline or across the instance."""
    statement = sa.select(WebhookTrigger).order_by(WebhookTrigger.pipeline_id, WebhookTrigger.code)
    if pipeline_id is not None:
        statement = statement.where(WebhookTrigger.pipeline_id == pipeline_id)
    if after is not None:
        statement = statement.where(WebhookTrigger.code > after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


HMAC_FIELD: Final = "hmac_secret"


def seal_hmac(secrets: "SecretBox | None", secret: SecretStr | None) -> tuple[bytes | None, str | None]:
    """Seal a webhook's signing secret with the instance key, the way a connection's is.

    ``secrets`` may be ``None`` only when there is nothing to seal; anything else is refused
    rather than stored in the clear, and so is an empty secret.
    """
    if secret is None:
        return None, None
    if not secret.get_secret_value():
        raise WebhookError(EMPTY_SIGNING_SECRET)
    if secrets is None:  # pragma: no cover - no caller can reach this
        raise WebhookError(NO_SECRET_KEY)
    return secrets.seal({HMAC_FIELD: secret.get_secret_value()}), secrets.key_id


def open_hmac(secrets: "SecretBox", webhook: WebhookTrigger) -> bytes | None:
    """Open a webhook's sealed signing secret."""
    if webhook.hmac_secret is None:
        return None
    opened = secrets.open(webhook.hmac_secret, key_id=webhook.hmac_secret_key_id)
    value = opened.get(HMAC_FIELD)
    return value.encode() if isinstance(value, str) else None


async def create_webhook(
    session: AsyncSession,
    pipeline: Pipeline,
    request: WebhookRequest,
    *,
    secrets: "SecretBox | None" = None,
) -> MintedToken:
    """Declare a webhook and mint its token, which is returned here and never again."""
    if await find_webhook(session, pipeline.id, request.code) is not None:
        raise DuplicateWebhook(pipeline=repr(pipeline.code), code=repr(request.code))
    token = mint_token()
    envelope, key_id = seal_hmac(secrets, request.hmac_secret)
    webhook = WebhookTrigger(
        pipeline_id=pipeline.id,
        code=request.code,
        name=request.name,
        description=request.description,
        token_hash=hash_token(token),
        token_prefix=token[:PREFIX_LENGTH],
        hmac_secret=envelope,
        hmac_secret_key_id=key_id,
        params_from_payload=dict(request.params_from_payload),
        rate_limit_per_minute=request.rate_limit_per_minute,
        priority=request.priority,
    )
    session.add(webhook)
    await session.flush()
    _logger.info("webhook created", pipeline=pipeline.code, webhook=webhook.code)
    return MintedToken(webhook_id=webhook.id, code=webhook.code, token=SecretStr(token), prefix=webhook.token_prefix)


async def update_webhook(
    session: AsyncSession,
    webhook: WebhookTrigger,
    request: WebhookRequest,
    *,
    secrets: "SecretBox | None" = None,
) -> WebhookTrigger:
    """Redeclare a webhook's mapping and limits, keeping the token it already has.

    Re-applying a document must not rotate a token, or every sender holding one breaks. A
    request carrying no secret keeps the one already stored, and there is no value that clears
    it. The secret is sealed before anything else is written, so a refused one changes nothing.
    """
    if request.hmac_secret is not None:
        webhook.hmac_secret, webhook.hmac_secret_key_id = seal_hmac(secrets, request.hmac_secret)
    webhook.name = request.name
    webhook.description = request.description
    webhook.params_from_payload = dict(request.params_from_payload)
    webhook.rate_limit_per_minute = request.rate_limit_per_minute
    webhook.priority = request.priority
    await session.flush()
    return webhook


async def rotate_token(session: AsyncSession, webhook: WebhookTrigger) -> MintedToken:
    """Mint a new token for a webhook and forget the old one, immediately."""
    token = mint_token()
    webhook.token_hash = hash_token(token)
    webhook.token_prefix = token[:PREFIX_LENGTH]
    await session.flush()
    _logger.info("webhook token rotated", webhook=webhook.code)
    return MintedToken(webhook_id=webhook.id, code=webhook.code, token=SecretStr(token), prefix=webhook.token_prefix)


async def set_active(session: AsyncSession, webhook: WebhookTrigger, *, active: bool) -> WebhookTrigger:
    """Enable or disable a webhook without rotating or losing its token."""
    webhook.active = active
    await session.flush()
    return webhook


async def delete_webhook(session: AsyncSession, webhook: WebhookTrigger) -> None:
    """Remove a webhook; its delivery history goes with it."""
    code = webhook.code
    await session.delete(webhook)
    await session.flush()
    _logger.info("webhook deleted", webhook=code)


async def resolve_webhook(session: AsyncSession, token: str) -> WebhookTrigger | None:
    """Resolve a presented token to its webhook, or to nothing.

    The lookup is an indexed equality on a SHA-256, so its timing tells an attacker nothing
    about the token behind it. The compare afterwards guards against a collation that treats
    two different strings as equal.
    """
    presented = hash_token(token)
    found = await session.execute(sa.select(WebhookTrigger).where(WebhookTrigger.token_hash == presented))
    webhook = found.scalar_one_or_none()
    if webhook is None:
        return None
    return webhook if hmac.compare_digest(webhook.token_hash, presented) else None


async def list_deliveries(
    session: AsyncSession,
    webhook_id: UUID,
    *,
    after: int | None = None,
    limit: int | None = None,
) -> list[WebhookDelivery]:
    """Read a webhook's recent deliveries, newest first."""
    statement = (
        sa.select(WebhookDelivery).where(WebhookDelivery.webhook_id == webhook_id).order_by(WebhookDelivery.id.desc())
    )
    if after is not None:
        statement = statement.where(WebhookDelivery.id < after)
    if limit is not None:
        statement = statement.limit(limit)
    rows = await session.execute(statement)
    return list(rows.scalars())


def parse_body(body: bytes, *, max_bytes: int) -> JsonMap:
    """Read an inbound body as a JSON object, refusing anything too large or not an object."""
    if len(body) > max_bytes:
        # "at least", because the intake stops reading one byte past the limit rather than
        # buffering an unbounded body to measure it exactly.
        raise DeliveryRefused(BODY_TOO_LARGE, status=413, size=len(body), maximum=max_bytes)
    try:
        loaded: object = json.loads(body or b"{}")
    except ValueError as error:
        raise DeliveryRefused(BODY_NOT_JSON, detail=str(error)) from error
    if not isinstance(loaded, dict):
        raise DeliveryRefused(BODY_NOT_OBJECT, kind=type(loaded).__name__)
    return cast("JsonMap", loaded)


def _evidence(payload: JsonMap) -> JsonMap:
    """Keep enough of a body to explain what happened."""
    rendered = json.dumps(payload, default=str)
    if len(rendered) <= PAYLOAD_KEEP_BYTES:
        return payload
    return {"_truncated": True, "_bytes": len(rendered), "_head": rendered[:PAYLOAD_KEEP_BYTES]}


CREATED_STATUS: Final = 201
SKIPPED_STATUS: Final = 202


class Delivered(BaseModel):
    """What one inbound delivery amounted to: a run, a skip, or a refusal.

    A refusal is a returned value, not a raised exception: the delivery row recording why is
    written in the same transaction, and an escaping exception would roll it back.
    """

    model_config = ConfigDict(frozen=True)

    outcome: WebhookOutcome
    status: int = CREATED_STATUS
    run_id: UUID | None = None
    reason: str | None = None
    params: JsonMap = Field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        """Report whether this delivery was allowed in, whether or not it produced a run."""
        return self.outcome is not WebhookOutcome.REJECTED


async def deliver(
    session: AsyncSession,
    services: EngineServices,
    webhook: WebhookTrigger,
    *,
    body: bytes,
    signature: str | None = None,
    source: str | None = None,
) -> Delivered:
    """Verify, map, validate, and enqueue one inbound delivery, recording it either way.

    Every path through this function writes a delivery row.
    """
    try:
        run, params, payload = await _accept(session, services, webhook, body=body, signature=signature)
    except DeliveryRefused as refusal:
        _record(session, webhook, WebhookOutcome.REJECTED, source=source, reason=refusal.reason)
        webhook.last_delivery_at = utcnow()
        _logger.warning("webhook delivery rejected", webhook=webhook.code, reason=refusal.reason)
        return Delivered(outcome=WebhookOutcome.REJECTED, status=refusal.status, reason=refusal.public)
    outcome = WebhookOutcome.ACCEPTED if run is not None else WebhookOutcome.SKIPPED
    reason = None if run is not None else "a run of this pipeline is already in flight"
    _record(
        session,
        webhook,
        outcome,
        source=source,
        reason=reason,
        payload=payload,
        params=params,
        run_id=run.id if run else None,
    )
    webhook.last_delivery_at = utcnow()
    _logger.info(
        "webhook delivery accepted",
        webhook=webhook.code,
        outcome=outcome.value,
        run_id=str(run.id) if run else None,
    )
    return Delivered(
        outcome=outcome,
        status=CREATED_STATUS if run is not None else SKIPPED_STATUS,
        run_id=run.id if run else None,
        reason=reason,
        params=params,
    )


async def _accept(
    session: AsyncSession,
    services: EngineServices,
    webhook: WebhookTrigger,
    *,
    body: bytes,
    signature: str | None,
) -> tuple[Run | None, JsonMap, JsonMap]:
    """Do the work of one delivery: verify, map, validate, and create the run."""
    if not webhook.active:
        # Answered exactly as an unknown token is, so the holder of a revoked token cannot
        # learn that it used to address a real webhook.
        raise DeliveryRefused(WEBHOOK_DISABLED, status=404, public=UNKNOWN_TOKEN)
    expected_secret = open_hmac(services.secrets, webhook)
    if expected_secret is not None:
        verify_signature(expected_secret, body, signature)
    payload = parse_body(body, max_bytes=services.settings.webhook_max_payload)
    params = map_payload(webhook.params_from_payload, payload)

    pipeline = await session.get(Pipeline, webhook.pipeline_id)
    if pipeline is None:  # pragma: no cover - cascade removes the webhook
        raise DeliveryRefused(WEBHOOK_PIPELINE_GONE, status=404)
    if not pipeline.active:
        raise DeliveryRefused(WEBHOOK_PIPELINE_INACTIVE, status=409, code=repr(pipeline.code))
    if pipeline.current_version is None:
        raise DeliveryRefused(WEBHOOK_PIPELINE_NO_VERSIONS, status=409, code=repr(pipeline.code))
    version = await _current_version(session, pipeline)

    definition = load_definition(version.document)
    try:
        definition.validate_params(params, services.format_checker)
    except ParameterError as error:
        raise DeliveryRefused(WEBHOOK_PARAMS_REFUSED, status=422, detail=str(error)) from error
    try:
        run = await create_run(
            session,
            services,
            version,
            params=params,
            attribution=Attribution(kind=TriggerKind.WEBHOOK, id=webhook.id, label=f"webhook {webhook.code}"),
            priority=webhook.priority,
        )
    except RunCreationError as error:
        raise DeliveryRefused(WEBHOOK_RUN_REFUSED, status=409, detail=str(error)) from error
    return run, params, payload


async def _current_version(session: AsyncSession, pipeline: Pipeline) -> PipelineVersion:
    """Read the version a webhook-started run pins, which is always the current one."""
    found = await session.execute(
        sa.select(PipelineVersion).where(
            PipelineVersion.pipeline_id == pipeline.id, PipelineVersion.version == pipeline.current_version
        )
    )
    version = found.scalar_one_or_none()
    if version is None:  # pragma: no cover - current_version always names a row
        raise DeliveryRefused(WEBHOOK_PIPELINE_UNREADABLE, status=409, code=repr(pipeline.code))
    return version


def _record(
    session: AsyncSession,
    webhook: WebhookTrigger,
    outcome: WebhookOutcome,
    *,
    source: str | None,
    reason: str | None = None,
    payload: JsonMap | None = None,
    params: JsonMap | None = None,
    run_id: UUID | None = None,
) -> None:
    """Append one delivery row."""
    session.add(
        WebhookDelivery(
            webhook_id=webhook.id,
            run_id=run_id,
            created_at=utcnow(),
            outcome=outcome,
            reason=reason,
            payload=_evidence(payload) if payload is not None else None,
            mapped_params=params,
            source=source,
        )
    )
