"""Settling a reply node: rendered by the server the moment it is ready, never claimed by a worker.

A reply renders its status, headers, content type and body from the run's outputs, the way a
gate resolves its list. The attempt succeeds with what it rendered, and whether that is what
the caller was answered with is ``delivered``: the input's caller has to still be held, and
no other reply of the run may have answered first.
"""

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Final, cast

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_client.enums import AttemptKind, AttemptStatus
from dirigent_common import JsonMap
from dirigent_common.requests import media_type
from dirigent_core.artifacts import persist_output
from dirigent_core.engine.definition import PipelineDefinition, ReplyNode
from dirigent_core.engine.expansion import collect_errors, collect_outputs
from dirigent_core.engine.failure import Failure
from dirigent_core.engine.references import ReferenceScope, UnknownReference, resolve
from dirigent_core.engine.services import EngineServices
from dirigent_core.messages import REPLY_BODY_FROM, REPLY_REFUSED, REPLY_STATUS
from dirigent_core.models import Run, StepAttempt
from dirigent_core.storage import scratch_prefix
from dirigent_plugin import ErrorClass

JSON: Final = "application/json"

OCTET_STREAM: Final = "application/octet-stream"

#: How an attempt says it was entered by a request, rather than by a hand run.
VIA_REQUEST: Final = "request"

#: Statuses whose answer carries no body.
BODYLESS: Final = frozenset({204, 304})


def entered_attempt(attempts: Sequence[StepAttempt]) -> StepAttempt | None:
    """Find the source attempt a run was entered at, or nothing for a run with no sources."""
    return next((attempt for attempt in attempts if attempt.kind is AttemptKind.RECEIVED), None)


def encode_body(body: JsonValue, content_type: str) -> bytes:
    """Write a rendered body as the bytes it is sent as: a string as text under ``text/*``, else JSON."""
    if body is None:
        return b""
    media, params = media_type(content_type)
    if isinstance(body, str) and media is not None and media.startswith("text/"):
        return body.encode(params.get("charset") or "utf-8")
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()


async def settle_reply(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    definition: PipelineDefinition,
    attempt: StepAttempt,
    attempts: Sequence[StepAttempt],
    moment: datetime,
) -> None:
    """Render a ready reply and settle its attempt, succeeded with the answer or failed as ``rejected``."""
    name = attempt.step_name
    reply = definition.steps[name].reply
    attempt.started_at = moment
    attempt.finished_at = moment
    if reply is None:  # pragma: no cover - the walk hands this only a reply's attempt
        return
    try:
        rendered = await _render(session, services, run, definition, name, reply)
    except UnknownReference as error:
        _fail(
            attempt, Failure(code=error.code, message=str(error), params=error.params, error_class=ErrorClass.REJECTED)
        )
        return
    except _Unrenderable as failure:
        _fail(attempt, failure.failure)
        return
    rendered["delivered"] = await _deliverable(session, services, run, definition, attempt, attempts)
    await persist_output(
        session,
        await services.bound_storage(session),
        attempt,
        rendered,
        inline_max_bytes=services.settings.inline_artifact_max,
    )
    attempt.status = AttemptStatus.SUCCEEDED


class _Unrenderable(Exception):
    """A reply whose references resolved to something no answer can be made of."""

    def __init__(self, failure: Failure) -> None:
        """Carry the failure the attempt settles with."""
        super().__init__(failure.message)
        self.failure = failure


async def _render(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    definition: PipelineDefinition,
    name: str,
    reply: ReplyNode,
) -> JsonMap:
    """Resolve every reference a reply writes, and measure the body it will send."""
    scope = ReferenceScope(
        params=dict(run.params),
        outputs=await collect_outputs(session, run.id, definition),
        errors=await collect_errors(session, run.id, definition),
        scratch=scratch_prefix(services.settings.artifact_root, run.id),
        artifacts=services.storage.artifact_root,
        run_id=run.id,
        window_start=run.window_start,
        window_end=run.window_end,
    )
    status = resolve(cast("JsonValue", reply.status), scope)
    if isinstance(status, str) and status.strip().isdigit():
        status = int(status.strip())
    if not isinstance(status, int) or isinstance(status, bool) or not 200 <= status <= 599:
        raise _Unrenderable(Failure.rejected(REPLY_STATUS, step=repr(name), status=repr(status)))
    headers = {header.lower(): _as_text(resolve(value, scope)) for header, value in reply.headers.items()}
    rendered: JsonMap = {"status": status, "headers": cast("JsonValue", headers)}
    if reply.body_from is not None:
        uri = resolve(reply.body_from, scope)
        if not isinstance(uri, str) or "://" not in uri:
            raise _Unrenderable(Failure.rejected(REPLY_BODY_FROM, step=repr(name), value=repr(uri)))
        stat = await (await services.bound_storage(session)).stat(uri)
        if stat is None:
            raise _Unrenderable(Failure.rejected(REPLY_REFUSED, step=repr(name), detail=f"nothing is stored at {uri}"))
        rendered.update(
            content_type=reply.content_type or stat.content_type or OCTET_STREAM,
            body=None,
            body_from=uri,
            body_bytes=stat.size,
        )
        return rendered
    body = None if status in BODYLESS else resolve(reply.body, scope)
    content_type = reply.content_type or JSON
    rendered.update(content_type=content_type, body=body, body_bytes=len(encode_body(body, content_type)))
    return rendered


async def _deliverable(
    session: AsyncSession,
    services: EngineServices,
    run: Run,
    definition: PipelineDefinition,
    attempt: StepAttempt,
    attempts: Sequence[StepAttempt],
) -> bool:
    """Say whether this reply is the answer a held caller gets.

    A hand run and a kind that does not reply hold nobody, and a caller another reply of the
    run already answered is not answered twice.
    """
    entered = entered_attempt(attempts)
    if entered is None or (entered.input or {}).get("via") != VIA_REQUEST:
        return False
    node = definition.steps[entered.step_name].source
    kind = services.sources.get(node.kind) if node is not None else None
    if kind is None or not kind.spec.replies:
        return False
    for other in attempts:
        if other is attempt or other.status is not AttemptStatus.SUCCEEDED or other.block_id != attempt.block_id:
            continue
        if other.step_name in definition.replies and (other.output or {}).get("delivered") is True:
            return False
    return True


def _fail(attempt: StepAttempt, failure: Failure) -> None:
    """Settle a reply that could not be rendered as a failure no retry can fix."""
    attempt.status = AttemptStatus.FAILED
    attempt.error = failure.message
    attempt.error_code = failure.code
    attempt.error_params = failure.params or None
    attempt.error_class = failure.error_class.value


def _as_text(value: JsonValue) -> str:
    """Render a resolved header value as the text a header carries."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        return json.dumps(value, separators=(",", ":"))
    return str(value)
