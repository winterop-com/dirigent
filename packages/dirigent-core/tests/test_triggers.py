"""Inbound webhooks, and what applying a document does to a pipeline's triggers."""

import json
from datetime import timedelta
from uuid import UUID

import pytest
import sqlalchemy as sa
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import ScheduleKind, TriggerKind, WebhookOutcome
from dirigent_client.schemas import PlanAction
from dirigent_core.config import Settings
from dirigent_core.database import session_scope
from dirigent_core.documents import load_text
from dirigent_core.engine.definition import ConcurrencyPolicy, PipelineDefinition, StepDefinition
from dirigent_core.engine.runs import Attribution, create_run, save_pipeline
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Pipeline, PipelineVersion, Run, Schedule, WebhookDelivery, WebhookTrigger, utcnow
from dirigent_core.pipelines import apply_document, find_pipeline
from dirigent_core.plugins import PluginHost
from dirigent_core.ratelimit import TokenBucket
from dirigent_core.scheduler import claim_due, tick
from dirigent_core.secrets import SecretBox
from dirigent_core.triggers.schedules import (
    ScheduleError,
    ScheduleRequest,
    UnknownSchedule,
    create_schedule,
    find_schedule,
    list_schedules,
    set_paused,
)
from dirigent_core.triggers.webhooks import (
    PAYLOAD_KEEP_BYTES,
    PREFIX_LENGTH,
    SIGNATURE_HEADER,
    UNKNOWN_TOKEN,
    Delivered,
    DeliveryRefused,
    UnknownWebhook,
    WebhookError,
    WebhookRequest,
    check_webhook_mapping,
    create_webhook,
    delete_webhook,
    deliver,
    find_webhook,
    hash_token,
    list_deliveries,
    list_webhooks,
    map_payload,
    mint_token,
    open_hmac,
    parse_body,
    read_path,
    resolve_webhook,
    rotate_token,
    seal_hmac,
    set_active,
    sign,
    update_webhook,
    verify_signature,
)

#: A pipeline document with no triggers, which every materialization test starts from.
BASE = """
format: dirigent/v1
code: daily-load
steps:
  first:
    block: test.echo
    config: { value: one }
"""

#: The same pipeline, now declaring one schedule and one webhook.
WITH_TRIGGERS = (
    BASE
    + """
triggers:
  schedules:
    - code: nightly
      cron: "0 5 * * *"
      timezone: Europe/Oslo
  webhooks:
    - code: inbound
      params_from_payload:
        day: "$.day"
"""
)

SECRET = b"s3cr3t"


def one_step(name: str, *, concurrency: ConcurrencyPolicy = ConcurrencyPolicy.ALLOW) -> PipelineDefinition:
    """A one-step pipeline built from the fake blocks, taking any parameters at all."""
    return PipelineDefinition(
        code=name,
        concurrency=concurrency,
        steps={"first": StepDefinition(block="test.echo", config={"value": "one"})},
    )


def parameterised(name: str) -> PipelineDefinition:
    """A pipeline whose parameter schema a mapped payload has to satisfy."""
    return PipelineDefinition(
        code=name,
        params={"type": "object", "required": ["day"], "properties": {"day": {"type": "string"}}},
        steps={"first": StepDefinition(block="test.echo")},
    )


async def declare_webhook(
    sessions: async_sessionmaker[AsyncSession],
    definition: PipelineDefinition,
    request: WebhookRequest,
    *,
    secrets: SecretBox | None = None,
) -> tuple[UUID, UUID, str]:
    """Save a pipeline version and mint one webhook on it, returning the token exactly once."""
    async with session_scope(sessions) as session:
        version = await save_pipeline(session, definition)
        pipeline = await session.get(Pipeline, version.pipeline_id)
        assert pipeline is not None
        minted = await create_webhook(session, pipeline, request, secrets=secrets)
        return pipeline.id, minted.webhook_id, minted.token.get_secret_value()


async def deliver_once(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    webhook_id: UUID,
    *,
    body: bytes,
    signature: str | None = None,
    source: str | None = None,
) -> Delivered:
    """Deliver one payload in one transaction, the way the intake endpoint does."""
    async with session_scope(sessions) as session:
        webhook = await session.get(WebhookTrigger, webhook_id)
        assert webhook is not None
        return await deliver(session, services, webhook, body=body, signature=signature, source=source)


async def deliveries_of(sessions: async_sessionmaker[AsyncSession], webhook_id: UUID) -> list[WebhookDelivery]:
    """Read a webhook's delivery rows, newest first."""
    async with sessions() as session:
        return await list_deliveries(session, webhook_id)


async def runs_of(sessions: async_sessionmaker[AsyncSession], pipeline_id: UUID) -> list[Run]:
    """Read every run of a pipeline, oldest first."""
    async with sessions() as session:
        rows = await session.execute(
            sa.select(Run).where(Run.pipeline_id == pipeline_id).order_by(Run.created_at, Run.id)
        )
        return list(rows.scalars())


async def apply(sessions: async_sessionmaker[AsyncSession], services: EngineServices, text: str) -> object:
    """Apply one document, which is where a ``triggers:`` section becomes rows."""
    async with session_scope(sessions) as session:
        return await apply_document(session, services, load_text(text))


async def schedule_named(sessions: async_sessionmaker[AsyncSession], pipeline_name: str, name: str) -> Schedule | None:
    """Find one schedule by pipeline name and schedule name."""
    async with sessions() as session:
        pipeline = await find_pipeline(session, pipeline_name)
        assert pipeline is not None
        return await find_schedule(session, pipeline.id, name)


async def webhook_named(
    sessions: async_sessionmaker[AsyncSession], pipeline_name: str, name: str
) -> WebhookTrigger | None:
    """Find one webhook by pipeline name and webhook name."""
    async with sessions() as session:
        pipeline = await find_pipeline(session, pipeline_name)
        assert pipeline is not None
        return await find_webhook(session, pipeline.id, name)


# -- reading a payload -----------------------------------------------------------


def test_a_dollar_rooted_path_reads_a_nested_value() -> None:
    assert read_path({"a": {"b": "found"}}, "$.a.b") == "found"


def test_a_bare_dotted_path_reads_exactly_the_same_value() -> None:
    payload = {"a": {"b": "found"}}
    assert read_path(payload, "a.b") == read_path(payload, "$.a.b")


def test_a_numeric_segment_addresses_a_list_element() -> None:
    payload = {"items": [{"id": "first"}, {"id": "second"}]}
    assert read_path(payload, "$.items.1.id") == "second"


def test_an_index_past_the_end_of_a_list_is_refused() -> None:
    with pytest.raises(DeliveryRefused, match=r"the payload has no \$\.items\.9"):
        read_path({"items": [1]}, "$.items.9")


def test_a_missing_key_is_refused_and_the_message_names_what_was_there() -> None:
    with pytest.raises(DeliveryRefused) as refusal:
        read_path({"outer": {"beta": 1, "alpha": 2}}, "$.outer.gamma")
    assert str(refusal.value) == "the payload has no $.outer.gamma (alpha, beta)"
    assert refusal.value.status == 400


def test_a_path_that_walks_into_something_that_is_not_an_object_says_so() -> None:
    with pytest.raises(DeliveryRefused, match=r"the payload has no \$\.a\.b \(not an object\)"):
        read_path({"a": 5}, "$.a.b")


def test_a_path_that_addresses_nothing_at_all_is_refused() -> None:
    for path in ("", "$", "$.", "..."):
        with pytest.raises(DeliveryRefused, match="addresses nothing"):
            read_path({"a": 1}, path)


def test_a_mapping_turns_a_whole_body_into_run_parameters() -> None:
    payload = {"day": "2026-06-01", "batch": {"size": 10}, "tags": ["one", "two"]}
    mapping = {"day": "$.day", "size": "$.batch.size", "first_tag": "tags.0"}
    assert map_payload(mapping, payload) == {"day": "2026-06-01", "size": 10, "first_tag": "one"}


def test_a_mapping_that_declares_nothing_produces_no_parameters() -> None:
    assert map_payload({}, {"day": "2026-06-01"}) == {}


# -- checking a mapping before anything is delivered to it ------------------------


def pipeline_with(params: dict[str, object]) -> PipelineDefinition:
    """Build a definition carrying one parameter schema and nothing else worth reading."""
    return PipelineDefinition(code="mapped", params=params, steps={"a": StepDefinition(block="test.echo")})


CLOSED = pipeline_with(
    {
        "type": "object",
        "properties": {"day": {"type": "string"}, "environment": {"type": "string", "default": "staging"}},
        "required": ["day", "environment"],
    }
)


@pytest.mark.parametrize(
    ("path", "problem"),
    [
        ("run.date", "it does not start with '$'"),
        ("$", "it addresses nothing"),
        ("$run.date", "the root is followed by 'r' rather than '.'"),
        ("$.run..date", "an empty segment"),
        ("$.run.date.", "an empty segment"),
    ],
)
def test_a_path_the_grammar_does_not_admit_is_refused_by_name(path: str, problem: str) -> None:
    with pytest.raises(WebhookError) as refusal:
        check_webhook_mapping(CLOSED, {"day": path})
    assert str(refusal.value) == f"{path!r} is not a payload path: {problem}"


def test_a_name_the_parameter_schema_does_not_declare_is_refused_beside_the_ones_it_does() -> None:
    with pytest.raises(WebhookError) as refusal:
        check_webhook_mapping(CLOSED, {"day": "$.run.date", "nonsense": "$.run.nonsense"})
    assert str(refusal.value) == "'nonsense' is not a parameter this pipeline declares (day, environment)"


def test_a_required_parameter_without_a_default_must_be_mapped_and_one_with_a_default_need_not_be() -> None:
    with pytest.raises(WebhookError) as refusal:
        check_webhook_mapping(CLOSED, {})
    assert str(refusal.value) == "the required parameter 'day' is not mapped, so no delivery could supply it"

    check_webhook_mapping(CLOSED, {"day": "$.run.date"})


def test_every_problem_in_one_mapping_is_reported_at_once() -> None:
    with pytest.raises(WebhookError) as refusal:
        check_webhook_mapping(CLOSED, {"nonsense": "$.a..b"})
    assert str(refusal.value).count("; ") == 2


def test_an_open_schema_takes_any_name_and_requires_none() -> None:
    """A pipeline declaring no parameters is what every document without a ``params`` gets."""
    check_webhook_mapping(pipeline_with({}), {"anything": "$.a.0.b"})
    check_webhook_mapping(pipeline_with({"type": "object"}), {"anything": "$.a"})
    check_webhook_mapping(PipelineDefinition(code="bare", steps={"a": StepDefinition(block="test.echo")}), {"a": "$.a"})


def test_a_schema_declaring_no_properties_and_forbidding_the_rest_takes_no_name() -> None:
    closed = pipeline_with({"type": "object", "additionalProperties": False})
    with pytest.raises(WebhookError, match=r"'anything' is not a parameter this pipeline declares \(none\)"):
        check_webhook_mapping(closed, {"anything": "$.a"})


# -- the token is the credential -------------------------------------------------


async def test_a_minted_token_resolves_to_its_webhook_and_a_wrong_one_resolves_to_nothing(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    _, webhook_id, token = await declare_webhook(sessions, one_step("hooked"), WebhookRequest(code="inbound"))
    async with sessions() as session:
        resolved = await resolve_webhook(session, token)
        assert resolved is not None
        assert resolved.id == webhook_id
        assert await resolve_webhook(session, mint_token()) is None
        assert await resolve_webhook(session, token + "x") is None


async def test_the_stored_row_holds_only_the_hash_and_a_prefix(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    _, webhook_id, token = await declare_webhook(sessions, one_step("hooked"), WebhookRequest(code="inbound"))
    async with sessions() as session:
        webhook = await session.get(WebhookTrigger, webhook_id)
        assert webhook is not None
        assert webhook.token_hash == hash_token(token)
        assert webhook.token_prefix == token[:PREFIX_LENGTH]
        assert token not in webhook.token_hash
        assert len(webhook.token_prefix) == PREFIX_LENGTH


async def test_rotating_a_token_invalidates_the_old_one_and_issues_one_that_resolves(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    _, webhook_id, old = await declare_webhook(sessions, one_step("hooked"), WebhookRequest(code="inbound"))
    async with session_scope(sessions) as session:
        webhook = await session.get(WebhookTrigger, webhook_id)
        assert webhook is not None
        minted = await rotate_token(session, webhook)
        new = minted.token.get_secret_value()

    assert new != old
    async with sessions() as session:
        assert await resolve_webhook(session, old) is None
        resolved = await resolve_webhook(session, new)
        assert resolved is not None
        assert resolved.token_prefix == new[:PREFIX_LENGTH]


async def test_a_second_webhook_of_the_same_name_on_one_pipeline_is_refused(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    pipeline_id, _, _ = await declare_webhook(sessions, one_step("hooked"), WebhookRequest(code="inbound"))
    async with session_scope(sessions) as session:
        pipeline = await session.get(Pipeline, pipeline_id)
        assert pipeline is not None
        with pytest.raises(WebhookError, match="already has a webhook coded 'inbound'"):
            await create_webhook(session, pipeline, WebhookRequest(code="inbound"))


async def test_webhooks_can_be_listed_and_deleted(sessions: async_sessionmaker[AsyncSession]) -> None:
    pipeline_id, webhook_id, _ = await declare_webhook(sessions, one_step("hooked"), WebhookRequest(code="inbound"))
    async with sessions() as session:
        assert [webhook.code for webhook in await list_webhooks(session, pipeline_id)] == ["inbound"]
        assert [webhook.code for webhook in await list_webhooks(session)] == ["inbound"]

    async with session_scope(sessions) as session:
        webhook = await session.get(WebhookTrigger, webhook_id)
        assert webhook is not None
        await delete_webhook(session, webhook)
    async with sessions() as session:
        assert await list_webhooks(session) == []


# -- the signature ---------------------------------------------------------------


def test_a_correct_signature_passes_and_a_wrong_one_is_refused() -> None:
    body = b'{"day": "2026-06-01"}'
    verify_signature(SECRET, body, sign(SECRET, body))
    with pytest.raises(DeliveryRefused, match="the signature does not match the body") as refusal:
        verify_signature(SECRET, body, sign(b"another-secret", body))
    assert refusal.value.status == 401


def test_a_missing_signature_is_refused_when_a_secret_is_set() -> None:
    for presented in (None, ""):
        with pytest.raises(DeliveryRefused) as refusal:
            verify_signature(SECRET, b"{}", presented)
        assert SIGNATURE_HEADER in str(refusal.value)
        assert refusal.value.status == 401


def test_the_sha256_prefixed_form_several_senders_write_is_accepted() -> None:
    body = b'{"day": "2026-06-01"}'
    verify_signature(SECRET, body, f"sha256={sign(SECRET, body)}")
    verify_signature(SECRET, body, f"  {sign(SECRET, body)}  ".strip())


def test_a_signature_over_a_reserialization_of_the_parsed_body_does_not_verify() -> None:
    # The bytes as they arrived and a re-serialization of the parsed JSON are not the same
    # string.
    raw = b'{"day":   "2026-06-01",  "n": 1}'
    reserialized = json.dumps(json.loads(raw)).encode()
    assert reserialized != raw
    verify_signature(SECRET, raw, sign(SECRET, raw))
    with pytest.raises(DeliveryRefused, match="does not match the body"):
        verify_signature(SECRET, raw, sign(SECRET, reserialized))


# -- the rate limiter ------------------------------------------------------------


def test_a_bucket_allows_up_to_the_limit_and_then_refuses() -> None:
    bucket = TokenBucket()
    assert [bucket.allow("token", per_minute=3, now=0.0) for _ in range(3)] == [True, True, True]
    assert bucket.allow("token", per_minute=3, now=0.0) is False


def test_a_bucket_refills_as_time_passes() -> None:
    bucket = TokenBucket()
    for _ in range(2):
        assert bucket.allow("token", per_minute=2, now=0.0) is True
    assert bucket.allow("token", per_minute=2, now=0.0) is False
    # Two a minute is one every thirty seconds, so half a minute buys exactly one more.
    assert bucket.allow("token", per_minute=2, now=29.0) is False
    assert bucket.allow("token", per_minute=2, now=60.0) is True


def test_one_key_going_too_fast_does_not_slow_another_down() -> None:
    bucket = TokenBucket()
    assert bucket.allow("first", per_minute=1, now=0.0) is True
    assert bucket.allow("first", per_minute=1, now=0.0) is False
    assert bucket.allow("second", per_minute=1, now=0.0) is True


def test_a_forgotten_key_starts_over_with_a_full_bucket() -> None:
    bucket = TokenBucket()
    assert bucket.allow("token", per_minute=1, now=0.0) is True
    assert bucket.allow("token", per_minute=1, now=0.0) is False
    bucket.forget("token")
    assert bucket.allow("token", per_minute=1, now=0.0) is True


def test_a_bucket_left_to_its_own_clock_still_allows_the_first_call() -> None:
    assert TokenBucket().allow("token", per_minute=1) is True


# -- reading the body ------------------------------------------------------------


def test_a_json_object_body_parses_and_an_empty_one_reads_as_no_payload() -> None:
    assert parse_body(b'{"day": "2026-06-01"}', max_bytes=1024) == {"day": "2026-06-01"}
    assert parse_body(b"", max_bytes=1024) == {}


def test_a_body_that_is_not_a_json_object_is_refused() -> None:
    with pytest.raises(DeliveryRefused, match="a webhook payload is a JSON object, not list") as refusal:
        parse_body(b"[1, 2]", max_bytes=1024)
    assert refusal.value.status == 400


def test_a_malformed_body_is_refused_as_not_json() -> None:
    with pytest.raises(DeliveryRefused, match="the body is not JSON"):
        parse_body(b"{not json", max_bytes=1024)


def test_a_body_larger_than_this_instance_reads_is_refused_with_413() -> None:
    with pytest.raises(DeliveryRefused) as refusal:
        parse_body(b'{"day": "2026-06-01"}', max_bytes=4)
    assert refusal.value.status == 413
    assert "and this instance reads at most 4" in str(refusal.value)


async def test_an_oversized_delivery_is_refused_and_recorded(
    sessions: async_sessionmaker[AsyncSession], settings: Settings, host: PluginHost
) -> None:
    _, webhook_id, _ = await declare_webhook(sessions, one_step("hooked"), WebhookRequest(code="inbound"))
    tight = EngineServices.build(settings.model_copy(update={"webhook_max_payload": 8}), host)

    delivered = await deliver_once(sessions, tight, webhook_id, body=b'{"day": "2026-06-01"}')

    assert delivered.outcome is WebhookOutcome.REJECTED
    assert delivered.status == 413
    assert len(await deliveries_of(sessions, webhook_id)) == 1


# -- one delivery, end to end ----------------------------------------------------


async def test_a_good_payload_starts_a_run_and_records_an_accepted_delivery(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    pipeline_id, webhook_id, _ = await declare_webhook(
        sessions,
        parameterised("strict-load"),
        WebhookRequest(code="inbound", params_from_payload={"day": "$.batch.day"}),
    )

    delivered = await deliver_once(
        sessions, services, webhook_id, body=b'{"batch": {"day": "2026-06-01"}}', source="203.0.113.7"
    )

    assert delivered.outcome is WebhookOutcome.ACCEPTED
    assert delivered.accepted is True
    assert delivered.status == 201
    assert delivered.params == {"day": "2026-06-01"}
    assert delivered.reason is None

    runs = await runs_of(sessions, pipeline_id)
    assert len(runs) == 1
    assert runs[0].id == delivered.run_id
    assert runs[0].triggered_by_kind is TriggerKind.WEBHOOK
    assert runs[0].triggered_by_id == webhook_id
    assert runs[0].triggered_by_label == "webhook inbound"
    assert runs[0].params == {"day": "2026-06-01"}

    recorded = await deliveries_of(sessions, webhook_id)
    assert len(recorded) == 1
    delivery = recorded[0]
    assert delivery.outcome is WebhookOutcome.ACCEPTED
    assert delivery.mapped_params == {"day": "2026-06-01"}
    assert delivery.payload == {"batch": {"day": "2026-06-01"}}
    assert delivery.run_id == delivered.run_id
    assert delivery.source == "203.0.113.7"

    async with sessions() as session:
        webhook = await session.get(WebhookTrigger, webhook_id)
        assert webhook is not None
        assert webhook.last_delivery_at is not None


async def test_a_payload_the_parameter_schema_rejects_leaves_its_evidence_behind(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    pipeline_id, webhook_id, _ = await declare_webhook(
        sessions,
        parameterised("strict-load"),
        WebhookRequest(code="inbound", params_from_payload={"day": "$.day"}),
    )

    delivered = await deliver_once(sessions, services, webhook_id, body=b'{"day": 5}')

    assert delivered.outcome is WebhookOutcome.REJECTED
    assert delivered.accepted is False
    assert delivered.reason is not None
    assert "does not satisfy the pipeline's parameters" in delivered.reason
    # The refusal is returned rather than raised precisely so this row commits.
    recorded = await deliveries_of(sessions, webhook_id)
    assert len(recorded) == 1
    assert recorded[0].outcome is WebhookOutcome.REJECTED
    assert recorded[0].reason == delivered.reason
    assert recorded[0].run_id is None
    assert await runs_of(sessions, pipeline_id) == []
    assert delivered.status == 422


async def test_a_pipeline_whose_parameter_schema_is_broken_refuses_the_delivery_and_records_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """An exception escaping deliver() would roll the delivery row back and leave no trace."""
    broken = PipelineDefinition(
        code="mistyped",
        params={"type": "objcet"},
        steps={"first": StepDefinition(block="test.echo")},
    )
    pipeline_id, webhook_id, _ = await declare_webhook(
        sessions, broken, WebhookRequest(code="inbound", params_from_payload={"day": "$.day"})
    )

    delivered = await deliver_once(sessions, services, webhook_id, body=b'{"day": "2026-08-28"}')

    assert delivered.outcome is WebhookOutcome.REJECTED
    assert delivered.status == 422
    assert delivered.reason is not None
    assert "parameter schema is not itself valid JSON Schema" in delivered.reason
    recorded = await deliveries_of(sessions, webhook_id)
    assert len(recorded) == 1
    assert recorded[0].outcome is WebhookOutcome.REJECTED
    assert recorded[0].reason == delivered.reason
    assert await runs_of(sessions, pipeline_id) == []


async def test_a_disabled_webhook_refuses_the_delivery_and_records_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    pipeline_id, webhook_id, _ = await declare_webhook(sessions, one_step("hooked"), WebhookRequest(code="inbound"))
    async with session_scope(sessions) as session:
        webhook = await session.get(WebhookTrigger, webhook_id)
        assert webhook is not None
        assert (await set_active(session, webhook, active=False)).active is False

    delivered = await deliver_once(sessions, services, webhook_id, body=b"{}")

    assert delivered.outcome is WebhookOutcome.REJECTED
    # The caller is told exactly what an unknown token is told, so the holder of a revoked
    # token cannot learn that it once addressed something real.
    assert delivered.status == 404
    assert delivered.reason == UNKNOWN_TOKEN
    recorded = await deliveries_of(sessions, webhook_id)
    assert len(recorded) == 1
    assert recorded[0].reason == "this webhook is disabled"
    assert await runs_of(sessions, pipeline_id) == []


async def test_a_deactivated_pipeline_refuses_the_delivery(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    pipeline_id, webhook_id, _ = await declare_webhook(sessions, one_step("switched-off"), WebhookRequest(code="in"))
    async with session_scope(sessions) as session:
        await session.execute(sa.update(Pipeline).where(Pipeline.id == pipeline_id).values(active=False))

    delivered = await deliver_once(sessions, services, webhook_id, body=b"{}")

    assert delivered.outcome is WebhookOutcome.REJECTED
    assert delivered.status == 409
    assert delivered.reason == "pipeline 'switched-off' is deactivated"
    assert await runs_of(sessions, pipeline_id) == []


async def test_a_pipeline_with_no_versions_yet_refuses_the_delivery(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        pipeline = Pipeline(code="versionless")
        session.add(pipeline)
        await session.flush()
        minted = await create_webhook(session, pipeline, WebhookRequest(code="inbound"))
        webhook_id = minted.webhook_id

    delivered = await deliver_once(sessions, services, webhook_id, body=b"{}")

    assert delivered.outcome is WebhookOutcome.REJECTED
    assert delivered.status == 409
    assert delivered.reason == "pipeline 'versionless' has no versions yet"


async def test_a_run_the_instance_refuses_to_create_is_refused_and_recorded(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    gated = PipelineDefinition(code="gated", steps={"run": StepDefinition(block="test.unsafe")})
    pipeline_id, webhook_id, _ = await declare_webhook(sessions, gated, WebhookRequest(code="inbound"))

    delivered = await deliver_once(sessions, services, webhook_id, body=b"{}")

    assert delivered.outcome is WebhookOutcome.REJECTED
    assert delivered.status == 409
    assert delivered.reason is not None
    assert "executes code on the worker and is disabled" in delivered.reason
    assert len(await deliveries_of(sessions, webhook_id)) == 1
    assert await runs_of(sessions, pipeline_id) == []


async def test_redeclaring_a_webhook_can_replace_its_secret_and_keeps_its_token(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    _, webhook_id, token = await declare_webhook(sessions, one_step("hooked"), WebhookRequest(code="inbound"))
    async with session_scope(sessions) as session:
        webhook = await session.get(WebhookTrigger, webhook_id)
        assert webhook is not None
        await update_webhook(
            session,
            webhook,
            WebhookRequest(
                code="inbound",
                params_from_payload={"day": "$.day"},
                hmac_secret=SecretStr(SECRET.decode()),
                rate_limit_per_minute=5,
            ),
            secrets=services.secrets,
        )

    async with sessions() as session:
        resolved = await resolve_webhook(session, token)
        assert resolved is not None
        assert resolved.hmac_secret != SECRET, "the signing secret is sealed, never stored in the clear"
        assert open_hmac(services.secrets, resolved) == SECRET
        assert resolved.rate_limit_per_minute == 5
        assert resolved.params_from_payload == {"day": "$.day"}


async def test_an_empty_secret_cannot_downgrade_a_signed_webhook_to_an_unverified_one(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The row would keep reading as signed while every delivery walked past verification."""
    _, webhook_id, _ = await declare_webhook(
        sessions,
        one_step("signed"),
        WebhookRequest(code="inbound", hmac_secret=SecretStr(SECRET.decode())),
        secrets=services.secrets,
    )
    with pytest.raises(ValidationError):
        WebhookRequest(code="inbound", hmac_secret=SecretStr(""))

    async with session_scope(sessions) as session:
        webhook = await session.get(WebhookTrigger, webhook_id)
        assert webhook is not None
        with pytest.raises(WebhookError):
            # A caller that skipped validation reaches the same refusal.
            await update_webhook(
                session,
                webhook,
                WebhookRequest.model_construct(
                    code="inbound", params_from_payload={}, hmac_secret=SecretStr(""), rate_limit_per_minute=60
                ),
                secrets=services.secrets,
            )

    body = b'{"day": "2026-06-01"}'
    unsigned = await deliver_once(sessions, services, webhook_id, body=body)
    still_signed = await deliver_once(sessions, services, webhook_id, body=body, signature=sign(SECRET, body))

    assert unsigned.outcome is WebhookOutcome.REJECTED
    assert unsigned.status == 401
    assert still_signed.outcome is WebhookOutcome.ACCEPTED, "the secret it was declared with still verifies"

    async with sessions() as session:
        stored = await session.get(WebhookTrigger, webhook_id)
    assert stored is not None
    assert open_hmac(services.secrets, stored) == SECRET


def test_an_empty_signing_secret_is_refused_rather_than_sealed() -> None:
    with pytest.raises(WebhookError) as raised:
        seal_hmac(None, SecretStr(""))
    assert "not a secret" in str(raised.value)


def test_a_code_that_addresses_no_trigger_says_which_pipeline_it_looked_in() -> None:
    assert str(UnknownWebhook("daily-load", "inbound")) == "pipeline 'daily-load' has no webhook coded 'inbound'"
    assert str(UnknownSchedule("daily-load", "nightly")) == "pipeline 'daily-load' has no schedule coded 'nightly'"
    assert UnknownSchedule("daily-load", "nightly").code == "nightly"


async def test_a_skip_policy_accepts_the_delivery_and_starts_no_run(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    pipeline_id, webhook_id, _ = await declare_webhook(
        sessions, one_step("skipper", concurrency=ConcurrencyPolicy.SKIP), WebhookRequest(code="inbound")
    )
    async with session_scope(sessions) as session:
        found = await session.execute(sa.select(PipelineVersion).where(PipelineVersion.pipeline_id == pipeline_id))
        in_flight = await create_run(session, services, found.scalar_one(), attribution=Attribution())
        assert in_flight is not None
        in_flight_id = in_flight.id

    delivered = await deliver_once(sessions, services, webhook_id, body=b"{}")

    assert delivered.outcome is WebhookOutcome.SKIPPED
    assert delivered.accepted is True
    assert delivered.status == 202
    assert delivered.run_id is None
    assert delivered.reason == "a run of this pipeline is already in flight"
    assert [run.id for run in await runs_of(sessions, pipeline_id)] == [in_flight_id]
    recorded = await deliveries_of(sessions, webhook_id)
    assert recorded[0].outcome is WebhookOutcome.SKIPPED
    assert recorded[0].run_id is None


async def test_a_signed_webhook_refuses_a_delivery_that_presents_no_signature(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    _, webhook_id, _ = await declare_webhook(
        sessions,
        one_step("signed"),
        WebhookRequest(code="inbound", hmac_secret=SecretStr(SECRET.decode())),
        secrets=services.secrets,
    )
    body = b'{"day": "2026-06-01"}'

    unsigned = await deliver_once(sessions, services, webhook_id, body=body)
    signed = await deliver_once(sessions, services, webhook_id, body=body, signature=sign(SECRET, body))

    assert unsigned.outcome is WebhookOutcome.REJECTED
    assert unsigned.status == 401
    assert signed.outcome is WebhookOutcome.ACCEPTED
    assert len(await deliveries_of(sessions, webhook_id)) == 2


async def test_a_non_ascii_signature_is_refused_and_leaves_a_delivery_row(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A header is attacker-controlled, and a 500 is evidence-free."""
    _, webhook_id, _ = await declare_webhook(
        sessions,
        one_step("signed"),
        WebhookRequest(code="inbound", hmac_secret=SecretStr(SECRET.decode())),
        secrets=services.secrets,
    )

    delivered = await deliver_once(sessions, services, webhook_id, body=b"{}", signature="sha256=\u00e6\u00f8\u00e5")

    assert delivered.outcome is WebhookOutcome.REJECTED
    assert delivered.status == 401
    assert len(await deliveries_of(sessions, webhook_id)) == 1


def test_verifying_a_non_ascii_signature_refuses_rather_than_raising() -> None:
    with pytest.raises(DeliveryRefused) as raised:
        verify_signature(SECRET, b"{}", "\u00e6\u00f8\u00e5")
    assert raised.value.status == 401


async def test_a_signing_secret_is_sealed_at_rest(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """It is a credential the instance holds, so it gets the same envelope as every other."""
    _, webhook_id, _ = await declare_webhook(
        sessions,
        one_step("signed"),
        WebhookRequest(code="inbound", hmac_secret=SecretStr(SECRET.decode())),
        secrets=services.secrets,
    )
    async with sessions() as session:
        stored = await session.get(WebhookTrigger, webhook_id)
    assert stored is not None
    assert stored.hmac_secret is not None
    assert SECRET not in stored.hmac_secret
    assert stored.hmac_secret_key_id == services.secrets.key_id
    assert open_hmac(services.secrets, stored) == SECRET


async def test_a_body_too_big_to_keep_whole_is_recorded_as_truncated_evidence(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    _, webhook_id, _ = await declare_webhook(sessions, one_step("chatty"), WebhookRequest(code="inbound"))
    body = json.dumps({"blob": "x" * (PAYLOAD_KEEP_BYTES + 100)}).encode()

    delivered = await deliver_once(sessions, services, webhook_id, body=body)

    assert delivered.outcome is WebhookOutcome.ACCEPTED
    recorded = await deliveries_of(sessions, webhook_id)
    assert recorded[0].payload is not None
    assert recorded[0].payload["_truncated"] is True
    assert len(recorded[0].payload["_head"]) == PAYLOAD_KEEP_BYTES


# -- what an apply does to the triggers ------------------------------------------


async def test_applying_a_document_with_triggers_creates_them_and_marks_them_managed(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(WITH_TRIGGERS))

    assert result.triggers.schedules_created == ["nightly"]
    assert result.triggers.webhooks_created == ["inbound"]
    assert result.triggers.empty is False

    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    assert schedule.managed is True
    assert schedule.kind is ScheduleKind.CRON
    assert schedule.timezone == "Europe/Oslo"
    assert schedule.next_fire_at is not None

    webhook = await webhook_named(sessions, "daily-load", "inbound")
    assert webhook is not None
    assert webhook.managed is True
    assert webhook.params_from_payload == {"day": "$.day"}


async def test_a_document_that_declares_no_triggers_reconciles_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(BASE))
    assert result.triggers.empty is True
    async with sessions() as session:
        assert await list_schedules(session) == []
        assert await list_webhooks(session) == []


async def test_reapplying_an_unchanged_document_changes_nothing_and_keeps_the_next_firing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)
    before = await schedule_named(sessions, "daily-load", "nightly")
    assert before is not None
    first_fire_at = before.next_fire_at

    async with session_scope(sessions) as session:
        again = await apply_document(session, services, load_text(WITH_TRIGGERS))

    assert again.triggers.empty is True
    after = await schedule_named(sessions, "daily-load", "nightly")
    assert after is not None
    # Compared field by field rather than rewritten, so re-applying does not move every
    # firing to a new grid.
    assert after.next_fire_at == first_fire_at
    assert after.id == before.id


async def test_reapplying_an_unchanged_document_restores_a_schedule_deleted_by_hand(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The digest covers the document, not the instance, so convergence cannot stop at it."""
    await apply(sessions, services, WITH_TRIGGERS)
    before = await schedule_named(sessions, "daily-load", "nightly")
    assert before is not None
    async with session_scope(sessions) as session:
        row = await session.get(Schedule, before.id)
        assert row is not None
        await session.delete(row)
    assert await schedule_named(sessions, "daily-load", "nightly") is None

    async with session_scope(sessions) as session:
        again = await apply_document(session, services, load_text(WITH_TRIGGERS))

    assert again.plan.action is PlanAction.UNCHANGED
    assert again.triggers.schedules_created == ["nightly"]
    restored = await schedule_named(sessions, "daily-load", "nightly")
    assert restored is not None
    assert restored.cron == before.cron


async def test_reapplying_a_document_leaves_a_schedule_someone_paused_paused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)
    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    async with session_scope(sessions) as session:
        row = await session.get(Schedule, schedule.id)
        assert row is not None
        await set_paused(session, row, paused=True)

    changed = WITH_TRIGGERS.replace('cron: "0 5 * * *"', 'cron: "0 6 * * *"')
    await apply(sessions, services, changed)

    after = await schedule_named(sessions, "daily-load", "nightly")
    assert after is not None
    assert after.cron == "0 6 * * *"
    assert after.paused is True


async def test_a_plain_apply_creates_a_schedule_that_is_not_paused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)

    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    assert schedule.paused is False


async def test_a_paused_apply_creates_the_schedule_already_paused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(WITH_TRIGGERS), pause_schedules=True)

    assert result.triggers.schedules_created == ["nightly"]
    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    assert schedule.paused is True
    assert schedule.next_fire_at is not None


async def test_a_paused_apply_leaves_no_moment_in_which_a_due_schedule_could_fire(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The row is inserted paused, so the first tick that could see it already cannot fire it."""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(WITH_TRIGGERS), pause_schedules=True)
    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    assert schedule.next_fire_at is not None
    due = schedule.next_fire_at

    assert await tick(sessions, services, now=due) == []
    async with sessions() as session:
        assert await claim_due(session, due) == []
    assert await runs_of(sessions, schedule.pipeline_id) == []

    # The clock was genuinely due: resuming it makes the same tick fire.
    async with session_scope(sessions) as session:
        row = await session.get(Schedule, schedule.id)
        assert row is not None
        await set_paused(session, row, paused=False)
    resumed = await schedule_named(sessions, "daily-load", "nightly")
    assert resumed is not None
    assert resumed.next_fire_at is not None
    fired = await tick(sessions, services, now=resumed.next_fire_at)
    assert [entry.schedule for entry in fired] == ["nightly"]


async def test_reapplying_without_the_flag_leaves_a_resumed_schedule_running(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(WITH_TRIGGERS), pause_schedules=True)
    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    async with session_scope(sessions) as session:
        row = await session.get(Schedule, schedule.id)
        assert row is not None
        await set_paused(session, row, paused=False)

    changed = WITH_TRIGGERS.replace('cron: "0 5 * * *"', 'cron: "0 6 * * *"')
    await apply(sessions, services, changed)

    after = await schedule_named(sessions, "daily-load", "nightly")
    assert after is not None
    assert after.cron == "0 6 * * *"
    assert after.paused is False


async def test_reapplying_with_the_flag_does_not_re_pause_a_schedule_that_already_exists(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """--paused governs what an apply brings into being, never what already runs."""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(WITH_TRIGGERS), pause_schedules=True)
    schedule = await schedule_named(sessions, "daily-load", "nightly")
    assert schedule is not None
    async with session_scope(sessions) as session:
        row = await session.get(Schedule, schedule.id)
        assert row is not None
        await set_paused(session, row, paused=False)

    changed = WITH_TRIGGERS.replace('cron: "0 5 * * *"', 'cron: "0 7 * * *"')
    async with session_scope(sessions) as session:
        again = await apply_document(session, services, load_text(changed), pause_schedules=True)

    assert again.triggers.schedules_updated == ["nightly"]
    after = await schedule_named(sessions, "daily-load", "nightly")
    assert after is not None
    assert after.paused is False


async def test_a_schedule_dropped_from_the_document_is_retired(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)
    without = WITH_TRIGGERS.replace(
        """  schedules:
    - code: nightly
      cron: "0 5 * * *"
      timezone: Europe/Oslo
""",
        "",
    )

    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(without))

    assert result.triggers.schedules_removed == ["nightly"]
    assert await schedule_named(sessions, "daily-load", "nightly") is None
    assert await webhook_named(sessions, "daily-load", "inbound") is not None


async def test_a_webhook_dropped_from_the_document_is_retired(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)
    without = WITH_TRIGGERS.replace(
        """  webhooks:
    - code: inbound
      params_from_payload:
        day: "$.day"
""",
        "",
    )

    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(without))

    assert result.triggers.webhooks_removed == ["inbound"]
    assert await webhook_named(sessions, "daily-load", "inbound") is None
    assert await schedule_named(sessions, "daily-load", "nightly") is not None


async def test_a_schedule_created_by_hand_survives_an_apply_that_does_not_mention_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, BASE)
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        by_hand = await create_schedule(
            session, pipeline, ScheduleRequest(code="operators-own", interval=timedelta(minutes=15))
        )
        assert by_hand.managed is False

    await apply(sessions, services, WITH_TRIGGERS)

    survivor = await schedule_named(sessions, "daily-load", "operators-own")
    assert survivor is not None
    assert survivor.managed is False
    assert survivor.kind is ScheduleKind.INTERVAL
    assert await schedule_named(sessions, "daily-load", "nightly") is not None


async def test_an_existing_webhook_keeps_the_token_it_already_minted_through_an_apply(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, BASE)
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        minted = await create_webhook(session, pipeline, WebhookRequest(code="inbound"))
        token = minted.token.get_secret_value()

    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(WITH_TRIGGERS))

    # The declaration changed the mapping, so the row was redeclared; the token is not.
    assert result.triggers.webhooks_updated == ["inbound"]
    assert result.triggers.webhooks_created == []
    async with sessions() as session:
        resolved = await resolve_webhook(session, token)
        assert resolved is not None
        assert resolved.params_from_payload == {"day": "$.day"}
        assert resolved.managed is True


async def test_changing_a_schedules_clock_in_the_document_redeclares_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, WITH_TRIGGERS)
    changed = WITH_TRIGGERS.replace('cron: "0 5 * * *"\n      timezone: Europe/Oslo', "interval: 30m")

    before = utcnow()
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(changed))

    assert result.triggers.schedules_updated == ["nightly"]
    after = await schedule_named(sessions, "daily-load", "nightly")
    assert after is not None
    assert after.kind is ScheduleKind.INTERVAL
    assert after.interval_seconds == 1800
    assert after.cron is None
    assert after.timezone == "UTC"
    assert after.next_fire_at is not None
    assert before + timedelta(minutes=30) <= after.next_fire_at <= utcnow() + timedelta(minutes=30)


def test_a_bucket_evicts_rather_than_growing_for_every_key_a_stranger_invents() -> None:
    """Every user of this limiter keys on something the caller chooses."""
    bucket = TokenBucket(max_keys=8)
    for index in range(100):
        assert bucket.allow(f"key-{index}", per_minute=60) is True
    assert len(bucket.buckets) == 8
    assert "key-99" in bucket.buckets
    assert "key-0" not in bucket.buckets


async def test_an_interval_of_less_than_whole_seconds_is_refused_at_declaration_time(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The row holds whole seconds, so a fraction would be silently shortened or lost."""
    await apply(sessions, services, BASE)
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        with pytest.raises(ScheduleError, match="whole number of seconds") as fractional:
            await create_schedule(session, pipeline, ScheduleRequest(code="too-fine", interval=timedelta(seconds=1.5)))
        assert "1.5s" in str(fractional.value)
        with pytest.raises(ScheduleError, match="at least one") as sub_second:
            await create_schedule(
                session, pipeline, ScheduleRequest(code="too-short", interval=timedelta(milliseconds=500))
            )
        assert "0.5s" in str(sub_second.value)


async def test_a_whole_second_interval_is_stored_as_the_seconds_it_names(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, BASE)
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        schedule = await create_schedule(
            session, pipeline, ScheduleRequest(code="every-ninety", interval=timedelta(seconds=90))
        )
    assert schedule.kind is ScheduleKind.INTERVAL
    assert schedule.interval_seconds == 90
