"""Tests for the built-in channels: the process log, an outbound JSON POST, Slack, and email."""

import asyncio
import json
import logging
import socket
from collections.abc import Callable, Iterator
from datetime import timedelta
from email import message_from_bytes
from email.message import Message
from typing import Any
from uuid import UUID, uuid4

import aiosmtplib
import httpx2
import pytest
import structlog
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult, LoginPassword
from pydantic import SecretStr, ValidationError
from structlog.testing import capture_logs
from structlog.typing import EventDict

from dirigent_blocks.notifiers import (
    ALERT_LOGGER,
    SLACK_AUTH_TEST,
    SLACK_HEADER_LIMIT,
    SLACK_POST_MESSAGE,
    EmailConnectionKind,
    EmailNotifier,
    EmailNotifierConfig,
    LogNotifier,
    LogNotifierConfig,
    SlackConnectionKind,
    SlackError,
    SlackNotifier,
    SlackNotifierConfig,
    WebhookConnectionKind,
    WebhookNotifier,
    WebhookNotifierConfig,
    mail_of,
    payload_of,
    slack_body,
)
from dirigent_plugin import AlertMessage

RUN_ID = UUID("0192f0a0-1111-7000-8000-000000000001")

ENDPOINT = "http://alerts.test/hook"

SLACK_HOOK = "https://hooks.slack.test/services/T000/B000/xxxx"

BOT_TOKEN = "xoxb-000-not-a-real-token"


@pytest.fixture(autouse=True)
def _permissive_structlog() -> Iterator[None]:  # pyright: ignore[reportUnusedFunction]
    """Let every level through while a test runs, and restore the session's own configuration.

    ``capture_logs`` swaps the processors but leaves the wrapper class alone, so a suite that
    has already configured logging at INFO would silently swallow the debug-level assertion.
    """
    saved = structlog.get_config()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.DEBUG))
    yield
    structlog.configure(**saved)


def an_alert(
    *,
    subject: str = "nightly run failed",
    run_id: UUID | None = RUN_ID,
    pipeline: str | None = "nightly",
    url: str | None = "https://dirigent.test/runs/nightly",
) -> AlertMessage:
    """Build the message an alert rule hands a notifier."""
    return AlertMessage(
        event="run_failed",
        subject=subject,
        body="status: failed",
        run_id=run_id,
        pipeline=pipeline,
        url=url,
        context={"run": {"pipeline": pipeline}},
    )


class Responder:
    """Answers every request with one scripted response, and remembers what it was sent."""

    def __init__(self, response: httpx2.Response) -> None:
        """Script the answer the endpoint gives."""
        self.response = response
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        """Answer one request, keeping it for the assertions."""
        self.requests.append(request)
        return self.response


def intercept(monkeypatch: pytest.MonkeyPatch, responder: Callable[[httpx2.Request], httpx2.Response]) -> None:
    """Point the notifier's own client at a mock transport, keeping the arguments it passes."""
    real = httpx2.AsyncClient

    def build(**kwargs: Any) -> httpx2.AsyncClient:
        return real(transport=httpx2.MockTransport(responder), **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", build)


def alert_entries(entries: list[EventDict]) -> list[EventDict]:
    """Keep only the entries this module's assertions are about."""
    return [entry for entry in entries if entry.get("pipeline") is not None or "event_kind" in entry]


# -- the log notifier --------------------------------------------------------------


async def test_an_alert_reaches_the_process_log_with_the_facts_on_it() -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(), LogNotifierConfig())
    entry = alert_entries(entries)[0]
    assert entry["event"] == "nightly run failed"
    assert entry["event_kind"] == "run_failed"
    assert entry["run_id"] == str(RUN_ID)
    assert entry["pipeline"] == "nightly"
    assert entry["url"] == "https://dirigent.test/runs/nightly"
    assert entry["body"] == "status: failed"


@pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
async def test_an_alert_is_written_at_the_configured_level(level: str) -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(), LogNotifierConfig.model_validate({"level": level}))
    assert alert_entries(entries)[0]["log_level"] == level


async def test_the_default_level_is_the_one_an_operator_would_notice() -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(), LogNotifierConfig())
    assert alert_entries(entries)[0]["log_level"] == "warning"


async def test_an_alert_about_no_run_says_so_rather_than_inventing_an_id() -> None:
    with capture_logs() as entries:
        await LogNotifier().send(an_alert(run_id=None, pipeline=None, url=None), LogNotifierConfig())
    entry = [line for line in entries if "event_kind" in line][0]
    assert entry["run_id"] is None
    assert entry["pipeline"] is None
    assert entry["url"] is None


def test_the_channel_writes_under_the_logger_the_engine_configures() -> None:
    assert ALERT_LOGGER == "dirigent.alert"
    assert LogNotifier.id == "log"
    assert LogNotifier.config_model is LogNotifierConfig


@pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
def test_the_four_levels_are_accepted(level: str) -> None:
    assert LogNotifierConfig.model_validate({"level": level}).level == level


@pytest.mark.parametrize("level", ["critical", "trace", "WARNING", ""])
def test_anything_but_the_four_levels_is_refused(level: str) -> None:
    with pytest.raises(ValidationError):
        LogNotifierConfig.model_validate({"level": level})


# -- the webhook notifier ----------------------------------------------------------


async def test_an_alert_is_posted_to_the_configured_endpoint_as_json(monkeypatch: pytest.MonkeyPatch) -> None:
    responder = Responder(httpx2.Response(202))
    intercept(monkeypatch, responder)
    message = an_alert()
    await WebhookNotifier().send(message, WebhookNotifierConfig(url=ENDPOINT))
    request = responder.requests[0]
    assert request.method == "POST"
    assert str(request.url) == ENDPOINT
    assert json.loads(request.content) == payload_of(message)


async def test_a_bearer_credential_is_presented_when_one_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    responder = Responder(httpx2.Response(200))
    intercept(monkeypatch, responder)
    config = WebhookNotifierConfig(url=ENDPOINT, bearer_token=SecretStr("t0ken"))
    await WebhookNotifier().send(an_alert(), config)
    assert responder.requests[0].headers["authorization"] == "Bearer t0ken"


async def test_no_authorization_header_is_sent_without_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    responder = Responder(httpx2.Response(200))
    intercept(monkeypatch, responder)
    await WebhookNotifier().send(an_alert(), WebhookNotifierConfig(url=ENDPOINT))
    assert "authorization" not in responder.requests[0].headers


async def test_the_extra_headers_a_receiver_wants_reach_it(monkeypatch: pytest.MonkeyPatch) -> None:
    responder = Responder(httpx2.Response(200))
    intercept(monkeypatch, responder)
    config = WebhookNotifierConfig(url=ENDPOINT, headers={"X-Routing-Key": "ops"})
    await WebhookNotifier().send(an_alert(), config)
    assert responder.requests[0].headers["x-routing-key"] == "ops"


@pytest.mark.parametrize("status", [400, 401, 404, 422, 500, 503])
async def test_a_refused_delivery_raises_so_the_queue_owns_the_retry(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    responder = Responder(httpx2.Response(status, text="no"))
    intercept(monkeypatch, responder)
    with pytest.raises(httpx2.HTTPStatusError) as raised:
        await WebhookNotifier().send(an_alert(), WebhookNotifierConfig(url=ENDPOINT))
    assert f"HTTP {status}" in str(raised.value)
    assert raised.value.response.status_code == status


@pytest.mark.parametrize("status", [200, 201, 202, 204, 302])
async def test_anything_the_endpoint_accepts_is_a_delivery(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    intercept(monkeypatch, Responder(httpx2.Response(status)))
    await WebhookNotifier().send(an_alert(), WebhookNotifierConfig(url=ENDPOINT))


async def test_a_webhook_with_no_endpoint_says_where_to_set_one() -> None:
    with pytest.raises(ValueError, match="has no url"):
        await WebhookNotifier().send(an_alert(), WebhookNotifierConfig())


def test_a_webhook_timeout_has_to_be_positive() -> None:
    with pytest.raises(ValidationError):
        WebhookNotifierConfig(url=ENDPOINT, timeout=timedelta(0))


def test_the_webhook_config_keeps_its_credential_out_of_its_repr() -> None:
    config = WebhookNotifierConfig(url=ENDPOINT, bearer_token=SecretStr("t0ken"))
    assert "t0ken" not in repr(config)
    assert WebhookNotifier.id == "webhook"


async def test_an_empty_bearer_is_not_a_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    responder = Responder(httpx2.Response(200))
    intercept(monkeypatch, responder)
    config = WebhookNotifierConfig(url=ENDPOINT, bearer_token=SecretStr(""))
    await WebhookNotifier().send(an_alert(), config)
    assert "authorization" not in responder.requests[0].headers


# -- the webhook connection kind ---------------------------------------------------


async def test_the_check_reaches_the_endpoint_without_delivering_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    responder = Responder(httpx2.Response(200))
    intercept(monkeypatch, responder)
    report = await WebhookConnectionKind().check(WebhookNotifierConfig(url=ENDPOINT))
    assert report.healthy
    assert responder.requests[0].method == "HEAD"


async def test_an_endpoint_that_refuses_head_is_still_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    intercept(monkeypatch, Responder(httpx2.Response(405)))
    report = await WebhookConnectionKind().check(WebhookNotifierConfig(url=ENDPOINT))
    assert report.healthy
    assert "405" in (report.detail or "")


async def test_an_endpoint_that_is_broken_is_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    intercept(monkeypatch, Responder(httpx2.Response(503)))
    report = await WebhookConnectionKind().check(WebhookNotifierConfig(url=ENDPOINT))
    assert not report.healthy
    assert "503" in (report.detail or "")


async def test_a_webhook_connection_with_no_url_says_so() -> None:
    report = await WebhookConnectionKind().check(WebhookNotifierConfig())
    assert not report.healthy
    assert report.detail == "no url is configured"


# -- the payload -------------------------------------------------------------------


def test_the_payload_is_the_alert_message_itself() -> None:
    message = an_alert()
    assert payload_of(message) == {
        "event": "run_failed",
        "subject": "nightly run failed",
        "body": "status: failed",
        "run_id": str(RUN_ID),
        "pipeline": "nightly",
        "url": "https://dirigent.test/runs/nightly",
        "context": {"run": {"pipeline": "nightly"}},
    }


def test_the_payload_renders_the_run_id_as_a_string() -> None:
    run_id = uuid4()
    assert payload_of(an_alert(run_id=run_id))["run_id"] == str(run_id)


def test_the_payload_says_null_when_there_is_no_run() -> None:
    payload = payload_of(an_alert(run_id=None, pipeline=None, url=None))
    assert payload["run_id"] is None
    assert payload["pipeline"] is None
    assert payload["url"] is None


def test_the_payload_is_json_serialisable_as_it_stands() -> None:
    assert json.loads(json.dumps(payload_of(an_alert())))["subject"] == "nightly run failed"


# -- what Slack is sent ------------------------------------------------------------


def blocks_of(body: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """Keep the blocks of one kind out of a rendered Slack body."""
    return [block for block in body["blocks"] if block["type"] == kind]


def test_the_subject_is_the_header_and_the_fallback_text() -> None:
    body = slack_body(an_alert())
    assert body["text"] == "nightly run failed"
    assert blocks_of(body, "header")[0]["text"] == {"type": "plain_text", "text": "nightly run failed"}


def test_the_body_is_the_section_under_the_header() -> None:
    body = slack_body(an_alert())
    assert blocks_of(body, "section")[0]["text"] == {"type": "mrkdwn", "text": "status: failed"}


def test_the_context_line_carries_the_pipeline_in_code_formatting_and_the_event() -> None:
    element = blocks_of(slack_body(an_alert()), "context")[0]["elements"][0]
    assert element == {"type": "mrkdwn", "text": "`nightly` | run_failed"}


def test_an_alert_about_no_pipeline_has_the_event_alone_in_its_context() -> None:
    element = blocks_of(slack_body(an_alert(pipeline=None)), "context")[0]["elements"][0]
    assert element["text"] == "run_failed"


def test_a_run_url_becomes_a_button_that_opens_it() -> None:
    button = blocks_of(slack_body(an_alert()), "actions")[0]["elements"][0]
    assert button["type"] == "button"
    assert button["url"] == "https://dirigent.test/runs/nightly"
    assert button["text"] == {"type": "plain_text", "text": "Open the run"}


def test_an_alert_with_nowhere_to_link_has_no_button() -> None:
    assert blocks_of(slack_body(an_alert(url=None)), "actions") == []


def test_a_long_subject_is_cut_to_what_a_header_block_accepts() -> None:
    header = blocks_of(slack_body(an_alert(subject="x" * 400)), "header")[0]
    assert len(header["text"]["text"]) == SLACK_HEADER_LIMIT
    assert header["text"]["text"].endswith("...")


def test_the_body_is_json_serialisable_as_it_stands() -> None:
    assert json.loads(json.dumps(slack_body(an_alert())))["text"] == "nightly run failed"


# -- the slack notifier ------------------------------------------------------------


def slack_response(status: int = 200, **payload: Any) -> httpx2.Response:
    """Build the answer a Slack endpoint gives, which is HTTP 200 either way."""
    return httpx2.Response(status, json=payload or {"ok": True})


async def test_the_webhook_form_posts_the_blocks_to_the_incoming_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responder = Responder(httpx2.Response(200, text="ok"))
    intercept(monkeypatch, responder)
    message = an_alert()
    await SlackNotifier().send(message, SlackNotifierConfig(webhook_url=SecretStr(SLACK_HOOK)))
    request = responder.requests[0]
    assert request.method == "POST"
    assert str(request.url) == SLACK_HOOK
    assert json.loads(request.content) == slack_body(message)
    assert "authorization" not in request.headers


async def test_the_bot_form_posts_to_chat_post_message_with_the_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    responder = Responder(slack_response())
    intercept(monkeypatch, responder)
    message = an_alert()
    config = SlackNotifierConfig(bot_token=SecretStr(BOT_TOKEN), channel="#ops")
    await SlackNotifier().send(message, config)
    request = responder.requests[0]
    assert str(request.url) == SLACK_POST_MESSAGE
    assert request.headers["authorization"] == f"Bearer {BOT_TOKEN}"
    assert json.loads(request.content) == {**slack_body(message), "channel": "#ops"}


async def test_the_bot_form_reaches_a_channel_named_by_its_id(monkeypatch: pytest.MonkeyPatch) -> None:
    responder = Responder(slack_response())
    intercept(monkeypatch, responder)
    config = SlackNotifierConfig(bot_token=SecretStr(BOT_TOKEN), channel="C0123456789")
    await SlackNotifier().send(an_alert(), config)
    assert json.loads(responder.requests[0].content)["channel"] == "C0123456789"


async def test_a_refusal_slack_answers_two_hundred_with_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    intercept(monkeypatch, Responder(slack_response(ok=False, error="channel_not_found")))
    config = SlackNotifierConfig(bot_token=SecretStr(BOT_TOKEN), channel="#gone")
    with pytest.raises(SlackError, match="channel_not_found"):
        await SlackNotifier().send(an_alert(), config)


async def test_an_answer_that_is_not_a_slack_result_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    intercept(monkeypatch, Responder(httpx2.Response(200, json=["ok"])))
    config = SlackNotifierConfig(bot_token=SecretStr(BOT_TOKEN), channel="#ops")
    with pytest.raises(SlackError, match="not a result"):
        await SlackNotifier().send(an_alert(), config)


@pytest.mark.parametrize("status", [400, 403, 404, 429, 500, 503])
@pytest.mark.parametrize("form", ["webhook", "bot"])
async def test_a_refused_slack_delivery_raises_so_the_queue_owns_the_retry(
    monkeypatch: pytest.MonkeyPatch, status: int, form: str
) -> None:
    intercept(monkeypatch, Responder(httpx2.Response(status, text="no")))
    config = (
        SlackNotifierConfig(webhook_url=SecretStr(SLACK_HOOK))
        if form == "webhook"
        else SlackNotifierConfig(bot_token=SecretStr(BOT_TOKEN), channel="#ops")
    )
    with pytest.raises(httpx2.HTTPStatusError) as raised:
        await SlackNotifier().send(an_alert(), config)
    assert f"HTTP {status}" in str(raised.value)


async def test_a_slack_channel_with_no_credential_says_where_to_set_one() -> None:
    with pytest.raises(ValueError, match="no webhook_url and no bot_token"):
        await SlackNotifier().send(an_alert(), SlackNotifierConfig())


@pytest.mark.parametrize(
    "config",
    [
        {"webhook_url": SLACK_HOOK, "bot_token": BOT_TOKEN},
        {"webhook_url": SLACK_HOOK, "channel": "#ops"},
        {"bot_token": BOT_TOKEN},
        {"bot_token": BOT_TOKEN, "channel": ""},
    ],
)
def test_a_config_that_is_neither_of_the_two_forms_is_refused(config: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        SlackNotifierConfig.model_validate(config)


def test_a_form_that_left_the_channel_box_empty_is_a_webhook_and_not_a_contradiction() -> None:
    config = SlackNotifierConfig.model_validate({"webhook_url": SLACK_HOOK, "channel": ""})
    assert config.webhook_url is not None


def test_the_slack_config_declares_both_credentials_secret() -> None:
    schema = SlackNotifierConfig.model_json_schema()
    for name in ("webhook_url", "bot_token"):
        assert any(one.get("writeOnly") for one in schema["properties"][name]["anyOf"])
    assert SlackNotifier.id == "slack"
    assert SlackNotifier.config_model is SlackNotifierConfig


def test_the_slack_config_keeps_its_credentials_out_of_its_repr() -> None:
    config = SlackNotifierConfig(bot_token=SecretStr(BOT_TOKEN), channel="#ops")
    assert BOT_TOKEN not in repr(config)
    assert SLACK_HOOK not in repr(SlackNotifierConfig(webhook_url=SecretStr(SLACK_HOOK)))


async def test_a_slack_timeout_has_to_be_positive() -> None:
    with pytest.raises(ValidationError):
        SlackNotifierConfig(webhook_url=SecretStr(SLACK_HOOK), timeout=timedelta(0))


async def test_no_credential_reaches_a_log_line_or_a_raised_message(monkeypatch: pytest.MonkeyPatch) -> None:
    intercept(monkeypatch, Responder(slack_response(ok=False, error="invalid_auth")))
    config = SlackNotifierConfig(bot_token=SecretStr(BOT_TOKEN), channel="#ops")
    with capture_logs() as entries, pytest.raises(SlackError) as raised:
        await SlackNotifier().send(an_alert(), config)
    assert BOT_TOKEN not in str(raised.value)
    assert BOT_TOKEN not in repr(raised.value)
    assert BOT_TOKEN not in json.dumps(entries, default=str)


async def test_no_credential_reaches_a_raised_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    intercept(monkeypatch, Responder(httpx2.Response(500, text="no")))
    with capture_logs() as entries, pytest.raises(httpx2.HTTPStatusError) as raised:
        await SlackNotifier().send(an_alert(), SlackNotifierConfig(webhook_url=SecretStr(SLACK_HOOK)))
    assert SLACK_HOOK not in str(raised.value)
    assert SLACK_HOOK not in json.dumps(entries, default=str)


# -- the slack connection kind -----------------------------------------------------


async def test_a_bot_token_is_checked_by_asking_slack_who_it_is(monkeypatch: pytest.MonkeyPatch) -> None:
    responder = Responder(slack_response(ok=True, team="Ops"))
    intercept(monkeypatch, responder)
    config = SlackNotifierConfig(bot_token=SecretStr(BOT_TOKEN), channel="#ops")
    report = await SlackConnectionKind().check(config)
    assert str(responder.requests[0].url) == SLACK_AUTH_TEST
    assert responder.requests[0].headers["authorization"] == f"Bearer {BOT_TOKEN}"
    assert report.healthy is True
    assert report.detail == "authenticated to Ops"


async def test_a_token_slack_refuses_is_an_unhealthy_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    intercept(monkeypatch, Responder(slack_response(ok=False, error="invalid_auth")))
    config = SlackNotifierConfig(bot_token=SecretStr(BOT_TOKEN), channel="#ops")
    report = await SlackConnectionKind().check(config)
    assert report.healthy is False
    assert "invalid_auth" in (report.detail or "")


async def test_a_check_that_cannot_reach_slack_reports_rather_than_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route", request=request)

    intercept(monkeypatch, refuse)
    config = SlackNotifierConfig(bot_token=SecretStr(BOT_TOKEN), channel="#ops")
    report = await SlackConnectionKind().check(config)
    assert report.healthy is False
    assert "ConnectError" in (report.detail or "")


async def test_an_incoming_webhook_is_reported_as_unverifiable_without_a_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responder = Responder(slack_response())
    intercept(monkeypatch, responder)
    report = await SlackConnectionKind().check(SlackNotifierConfig(webhook_url=SecretStr(SLACK_HOOK)))
    assert responder.requests == []
    assert report.healthy is True
    assert "can only be checked by posting to it" in (report.detail or "")


def test_the_slack_connection_kind_is_the_notifier_s_own_config() -> None:
    assert SlackConnectionKind.id == "slack"
    assert SlackConnectionKind.config_model is SlackNotifierConfig


# -- what an alert is mailed as ----------------------------------------------------


def mail_settings(**overrides: Any) -> EmailNotifierConfig:
    """Build an email config that would submit, with anything a test cares about replaced."""
    fields: dict[str, Any] = {
        "host": "127.0.0.1",
        "security": "none",
        "from_address": "dirigent@ops.test",
        "to": ["oncall@ops.test"],
    }
    return EmailNotifierConfig.model_validate({**fields, **overrides})


def test_the_subject_carries_the_prefix_a_mail_rule_files_on() -> None:
    assert mail_of(mail_settings(), an_alert())["Subject"] == "[dirigent] nightly run failed"


def test_the_prefix_may_be_dropped_altogether() -> None:
    assert mail_of(mail_settings(subject_prefix=""), an_alert())["Subject"] == "nightly run failed"


def test_every_recipient_is_on_the_one_message() -> None:
    settings = mail_settings(to=["oncall@ops.test", "lead@ops.test"])
    assert mail_of(settings, an_alert())["To"] == "oncall@ops.test, lead@ops.test"
    assert mail_of(settings, an_alert())["From"] == "dirigent@ops.test"


def test_the_message_is_plain_text_and_nothing_else() -> None:
    mail = mail_of(mail_settings(), an_alert())
    assert mail.get_content_type() == "text/plain"
    assert mail.is_multipart() is False


def test_the_body_carries_the_alert_and_the_facts_under_it() -> None:
    body = mail_of(mail_settings(), an_alert()).get_content()
    assert body.splitlines() == [
        "nightly run failed",
        "",
        "status: failed",
        "",
        "pipeline: nightly",
        "event: run_failed",
        "url: https://dirigent.test/runs/nightly",
    ]


def test_an_alert_about_no_run_still_says_what_the_event_was() -> None:
    body = mail_of(mail_settings(), an_alert(run_id=None, pipeline=None, url=None)).get_content()
    assert "pipeline: -" in body
    assert "event: run_failed" in body
    assert "url:" not in body


# -- the email notifier, against a real in-process SMTP server ---------------------


class Mailbox:
    """An SMTP handler that keeps every message the notifier submits to it."""

    def __init__(self) -> None:
        """Start with nothing delivered."""
        self.envelopes: list[Any] = []

    async def handle_DATA(self, server: Any, session: Any, envelope: Any) -> str:  # noqa: N802 - aiosmtpd's name
        """Accept one message and keep it for the assertions."""
        self.envelopes.append(envelope)
        return "250 Message accepted for delivery"

    def messages(self) -> list[Message]:
        """Parse what was delivered back into messages."""
        return [message_from_bytes(envelope.content) for envelope in self.envelopes]


def authenticator(server: Any, session: Any, envelope: Any, mechanism: str, auth_data: Any) -> AuthResult:
    """Accept exactly one account, so a test can tell a login from an unauthenticated session."""
    expected = LoginPassword(b"postmaster", b"s3cret")
    return AuthResult(success=auth_data == expected, handled=False)


class Server:
    """One in-process SMTP server, and where it is listening."""

    def __init__(self, port: int, mailbox: Mailbox) -> None:
        """Hold where the server is listening and the mailbox behind it."""
        self.port = port
        self.mailbox = mailbox


def free_port() -> int:
    """Find a port nothing is listening on, because the controller wants one up front."""
    with socket.socket() as held:
        held.bind(("127.0.0.1", 0))
        return int(held.getsockname()[1])


@pytest.fixture
def smtp(request: pytest.FixtureRequest) -> Iterator[Server]:
    """Run a real SMTP server for one test, with authentication where the test asks for it."""
    wants_auth = getattr(request, "param", False)
    mailbox = Mailbox()
    port = free_port()
    controller = Controller(
        mailbox,
        hostname="127.0.0.1",
        port=port,
        # The fake speaks no TLS, so it has to be told a login on a plain session is allowed.
        authenticator=authenticator if wants_auth else None,
        auth_require_tls=False,
    )
    controller.start()
    try:
        yield Server(port, mailbox)
    finally:
        controller.stop()


async def test_an_alert_is_submitted_as_one_message(smtp: Server) -> None:
    await EmailNotifier().send(an_alert(), mail_settings(port=smtp.port))
    envelope = smtp.mailbox.envelopes[0]
    assert envelope.mail_from == "dirigent@ops.test"
    assert envelope.rcpt_tos == ["oncall@ops.test"]
    message = smtp.mailbox.messages()[0]
    assert message["Subject"] == "[dirigent] nightly run failed"
    assert message["To"] == "oncall@ops.test"
    assert message.get_content_type() == "text/plain"
    assert "status: failed" in message.get_payload()


async def test_every_recipient_is_delivered_to(smtp: Server) -> None:
    settings = mail_settings(port=smtp.port, to=["oncall@ops.test", "lead@ops.test"])
    await EmailNotifier().send(an_alert(), settings)
    assert smtp.mailbox.envelopes[0].rcpt_tos == ["oncall@ops.test", "lead@ops.test"]


@pytest.mark.parametrize("smtp", [True], indirect=True)
async def test_a_configured_account_logs_in_before_submitting(smtp: Server) -> None:
    settings = mail_settings(port=smtp.port, username="postmaster", password=SecretStr("s3cret"))
    await EmailNotifier().send(an_alert(), settings)
    assert len(smtp.mailbox.envelopes) == 1


@pytest.mark.parametrize("smtp", [True], indirect=True)
async def test_a_password_the_server_refuses_raises_rather_than_dropping_the_alert(smtp: Server) -> None:
    settings = mail_settings(port=smtp.port, username="postmaster", password=SecretStr("wrong"))
    with pytest.raises(aiosmtplib.SMTPAuthenticationError):
        await EmailNotifier().send(an_alert(), settings)
    assert smtp.mailbox.envelopes == []


async def test_a_refused_connection_raises_so_the_queue_owns_the_retry() -> None:
    with pytest.raises(aiosmtplib.SMTPConnectError):
        await EmailNotifier().send(an_alert(), mail_settings(port=free_port(), timeout=timedelta(seconds=2)))


async def test_a_server_that_does_not_offer_starttls_is_a_refusal_not_a_plaintext_send(smtp: Server) -> None:
    settings = mail_settings(port=smtp.port, security="starttls")
    with pytest.raises(aiosmtplib.SMTPException):
        await EmailNotifier().send(an_alert(), settings)
    assert smtp.mailbox.envelopes == []


async def test_an_implicit_tls_session_will_not_talk_to_a_plain_server(smtp: Server) -> None:
    settings = mail_settings(port=smtp.port, security="tls", timeout=timedelta(seconds=2))
    with pytest.raises((aiosmtplib.SMTPException, asyncio.TimeoutError, OSError)):
        await EmailNotifier().send(an_alert(), settings)
    assert smtp.mailbox.envelopes == []


@pytest.mark.parametrize(
    ("field", "value"),
    [("host", ""), ("from_address", ""), ("to", [])],
)
async def test_a_channel_missing_what_a_submission_needs_says_which(field: str, value: Any) -> None:
    with pytest.raises(ValueError, match=f"has no {field}"):
        await EmailNotifier().send(an_alert(), mail_settings(**{field: value}))


def test_the_email_config_declares_the_password_secret() -> None:
    schema = EmailNotifierConfig.model_json_schema()
    assert any(one.get("writeOnly") for one in schema["properties"]["password"]["anyOf"])
    assert EmailNotifier.id == "email"
    assert EmailNotifier.config_model is EmailNotifierConfig


def test_the_email_config_keeps_its_password_out_of_its_repr() -> None:
    assert "s3cret" not in repr(mail_settings(password=SecretStr("s3cret")))


def test_the_defaults_are_the_submission_a_modern_server_wants() -> None:
    settings = EmailNotifierConfig()
    assert settings.port == 587
    assert settings.security == "starttls"
    assert settings.subject_prefix == "[dirigent]"


@pytest.mark.parametrize(("port", "security"), [(0, "starttls"), (70000, "starttls"), (587, "ssl")])
def test_a_port_or_a_mode_no_server_speaks_is_refused(port: int, security: str) -> None:
    with pytest.raises(ValidationError):
        EmailNotifierConfig.model_validate({"host": "h", "port": port, "security": security})


# -- the email connection kind -----------------------------------------------------


async def test_a_check_connects_and_greets_without_mailing_anything(smtp: Server) -> None:
    report = await EmailConnectionKind().check(mail_settings(port=smtp.port))
    assert report.healthy is True
    assert "greeted" in (report.detail or "")
    assert smtp.mailbox.envelopes == []


@pytest.mark.parametrize("smtp", [True], indirect=True)
async def test_a_check_with_credentials_logs_in_without_mailing_anything(smtp: Server) -> None:
    settings = mail_settings(port=smtp.port, username="postmaster", password=SecretStr("s3cret"))
    report = await EmailConnectionKind().check(settings)
    assert report.healthy is True
    assert "authenticated" in (report.detail or "")
    assert smtp.mailbox.envelopes == []


@pytest.mark.parametrize("smtp", [True], indirect=True)
async def test_a_check_reports_a_password_the_server_refuses(smtp: Server) -> None:
    settings = mail_settings(port=smtp.port, username="postmaster", password=SecretStr("wrong"))
    report = await EmailConnectionKind().check(settings)
    assert report.healthy is False
    assert "SMTPAuthenticationError" in (report.detail or "")


async def test_a_check_that_cannot_reach_a_server_reports_rather_than_raises() -> None:
    report = await EmailConnectionKind().check(mail_settings(port=free_port(), timeout=timedelta(seconds=2)))
    assert report.healthy is False
    assert "SMTPConnectError" in (report.detail or "")


async def test_a_check_with_no_host_says_so_without_dialling() -> None:
    report = await EmailConnectionKind().check(EmailNotifierConfig())
    assert report.healthy is False
    assert report.detail == "no host is configured"


def test_the_email_connection_kind_is_the_notifier_s_own_config() -> None:
    assert EmailConnectionKind.id == "email"
    assert EmailConnectionKind.config_model is EmailNotifierConfig
