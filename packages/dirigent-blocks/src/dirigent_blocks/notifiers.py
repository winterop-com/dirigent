"""The notifiers a fresh install already has: the process log, an outbound POST, Slack, and email.

Every notifier but the log one registers a connection kind of the same id beside itself, so the
channel is minted, sealed and health-checked through the one connection path every credential
in this instance goes through.
"""

from datetime import timedelta
from email.message import EmailMessage
from typing import ClassVar, Literal

import aiosmtplib
import httpx2
import structlog
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, model_validator

from dirigent_common import BlockModel, Duration, HealthReport
from dirigent_plugin import AlertMessage, ConnectionKind, Notifier

#: Must match the logger chain dirigent-core configures.
ALERT_LOGGER = "dirigent.alert"

DEFAULT_TIMEOUT = timedelta(seconds=15)

FAILED_STATUS = 400

#: Where a health check stops calling an answer evidence that something is listening.
SERVER_ERROR_STATUS = 500


class LogNotifierConfig(BlockModel):
    """What the log notifier needs, which is nothing but the level to write at."""

    level: Literal["debug", "info", "warning", "error"] = "warning"
    """The process-log level an alert is written at; a channel with no credential has little else to say."""


class LogNotifier(Notifier):
    """Writes an alert to the process log, so an instance with no channel configured still says something."""

    id: ClassVar[str] = "log"
    config_model: ClassVar[type[BaseModel]] = LogNotifierConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Write one alert through the shared structlog chain, at the configured level."""
        settings = LogNotifierConfig.model_validate(config.model_dump())
        logger: structlog.stdlib.BoundLogger = structlog.get_logger(ALERT_LOGGER)
        write = getattr(logger, settings.level, logger.warning)
        write(
            message.subject,
            event_kind=message.event,
            run_id=str(message.run_id) if message.run_id else None,
            pipeline=message.pipeline,
            url=message.url,
            body=message.body,
        )


class WebhookNotifierConfig(BlockModel):
    """Where to POST an alert, and what to present when getting there."""

    url: str = Field(default="", description="The endpoint an alert is POSTed to as JSON.")
    """Where to send it; a connection supplies this, so a rule can name one endpoint per channel."""

    bearer_token: SecretStr | None = None
    """A bearer credential, sent as an Authorization header."""

    headers: dict[str, str] = Field(default_factory=dict[str, str])
    """Extra headers the receiving system wants, such as a routing key."""

    verify_tls: bool = True
    """Whether certificates are verified; turning this off is a per-connection decision."""

    timeout: Duration = Field(default=DEFAULT_TIMEOUT, gt=timedelta(0))
    """How long the POST may take before the delivery is retried."""


class WebhookNotifier(Notifier):
    """POSTs an alert as JSON, which reaches any system that can receive one."""

    id: ClassVar[str] = "webhook"
    config_model: ClassVar[type[BaseModel]] = WebhookNotifierConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Deliver one alert as a JSON POST, raising so the queue retries a refusal.

        Raising rather than swallowing is the contract: the notification row owns the retry
        budget and the backoff, so a notifier that quietly returned on a 500 would turn a
        recoverable blip into an alert nobody ever gets.
        """
        settings = WebhookNotifierConfig.model_validate(config.model_dump())
        if not settings.url:
            raise ValueError("the webhook notifier has no url; set one on the connection this rule delivers through")
        headers = _webhook_headers(settings)
        async with httpx2.AsyncClient(
            timeout=settings.timeout.total_seconds(),
            verify=settings.verify_tls,
            headers=headers,
        ) as client:
            response = await client.post(settings.url, json=payload_of(message))
        if response.status_code >= FAILED_STATUS:
            raise httpx2.HTTPStatusError(
                f"the alert endpoint answered HTTP {response.status_code}",
                request=response.request,
                response=response,
            )


def _webhook_headers(settings: WebhookNotifierConfig) -> dict[str, str]:
    """Render the headers one call presents, leaving out a bearer nobody set.

    A stored empty token is absent, not a credential: sending it verbatim builds
    ``Authorization: Bearer `` and httpx refuses to put an empty value on the wire.
    """
    headers = dict(settings.headers)
    token = settings.bearer_token.get_secret_value() if settings.bearer_token is not None else ""
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class WebhookConnectionKind(ConnectionKind):
    """The credential record the webhook channel delivers through."""

    id: ClassVar[str] = "webhook"
    config_model: ClassVar[type[BaseModel]] = WebhookNotifierConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Reach the endpoint without delivering anything, by asking for its headers alone.

        A HEAD proves the address resolves, the certificate is accepted and something is
        listening. It does not prove the endpoint accepts an alert, because the only thing
        that proves that is posting one -- so an endpoint that refuses HEAD is reported
        reachable rather than unhealthy.
        """
        settings = WebhookNotifierConfig.model_validate(config.model_dump())
        if not settings.url:
            return HealthReport(healthy=False, detail="no url is configured")
        headers = _webhook_headers(settings)
        try:
            async with httpx2.AsyncClient(
                timeout=settings.timeout.total_seconds(), verify=settings.verify_tls, headers=headers
            ) as client:
                response = await client.head(settings.url)
        # Broad on purpose: a health check reports a failure, it never raises one at the caller.
        except Exception as error:
            return HealthReport(healthy=False, detail=f"{type(error).__name__}: {error}")
        if response.status_code >= SERVER_ERROR_STATUS:
            return HealthReport(healthy=False, detail=f"the endpoint answered HTTP {response.status_code}")
        return HealthReport(healthy=True, detail=f"reachable: HEAD answered HTTP {response.status_code}")


def payload_of(message: AlertMessage) -> dict[str, object]:
    """Render an alert as the JSON body a receiving system reads."""
    return {
        "event": message.event,
        "subject": message.subject,
        "body": message.body,
        "run_id": str(message.run_id) if message.run_id else None,
        "pipeline": message.pipeline,
        "url": message.url,
        "context": message.context,
    }


#: Where the bot form posts a message.
SLACK_POST_MESSAGE = "https://slack.com/api/chat.postMessage"

#: Where the bot form proves its token.
SLACK_AUTH_TEST = "https://slack.com/api/auth.test"

#: Slack refuses a header block whose plain_text runs past this.
SLACK_HEADER_LIMIT = 150

#: Slack refuses a section or context block whose text runs past this.
SLACK_TEXT_LIMIT = 3000


class SlackError(RuntimeError):
    """What Slack said when it refused a message, carried so the queue's retry reads it."""


class SlackNotifierConfig(BlockModel):
    """Which of Slack's two doors an alert goes through, and the credential for it."""

    webhook_url: SecretStr | None = None
    """A Slack incoming webhook. It carries the destination channel inside it, so it is both
    the address and the credential, and it is sealed as one."""

    bot_token: SecretStr | None = None
    """A bot token, presented to ``chat.postMessage``. Needs ``channel`` beside it."""

    channel: str | None = None
    """Where ``chat.postMessage`` puts the message: a channel id, or ``#name``."""

    verify_tls: bool = True
    """Whether certificates are verified; turning this off is a per-connection decision."""

    timeout: Duration = Field(default=DEFAULT_TIMEOUT, gt=timedelta(0))
    """How long the call may take before the delivery is retried."""

    @model_validator(mode="after")
    def _check_one_form(self) -> "SlackNotifierConfig":
        """Refuse a config that names both doors, or a token with nowhere to post it."""
        if self.webhook_url is not None and self.bot_token is not None:
            raise ValueError("set webhook_url or bot_token, not both: they are two ways to reach the same channel")
        if self.webhook_url is not None and self.channel:
            raise ValueError("a webhook_url carries its own channel; drop channel or use bot_token instead")
        if self.bot_token is not None and not self.channel:
            raise ValueError("a bot_token needs a channel to post to: a channel id, or #name")
        return self


class SlackNotifier(Notifier):
    """Posts an alert to Slack, through an incoming webhook or through ``chat.postMessage``."""

    id: ClassVar[str] = "slack"
    config_model: ClassVar[type[BaseModel]] = SlackNotifierConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Deliver one alert to Slack, raising so the queue retries a refusal.

        Raising rather than swallowing is the contract: the notification row owns the retry
        budget and the backoff, so a notifier that quietly returned on a 500 would turn a
        recoverable blip into an alert nobody ever gets.
        """
        settings = SlackNotifierConfig.model_validate(config.model_dump())
        body = slack_body(message)
        if settings.webhook_url is not None:
            await _post_slack(settings, settings.webhook_url.get_secret_value(), body, token=None)
            return
        if settings.bot_token is not None:
            await _post_slack(
                settings,
                SLACK_POST_MESSAGE,
                {**body, "channel": settings.channel},
                token=settings.bot_token.get_secret_value(),
            )
            return
        raise ValueError(
            "the slack notifier has no webhook_url and no bot_token; "
            "set one on the connection this rule delivers through"
        )


class SlackConnectionKind(ConnectionKind):
    """The credential record the Slack channel delivers through."""

    id: ClassVar[str] = "slack"
    config_model: ClassVar[type[BaseModel]] = SlackNotifierConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Prove a bot token with ``auth.test``, and say why a webhook cannot be proved at all."""
        settings = SlackNotifierConfig.model_validate(config.model_dump())
        if settings.bot_token is None:
            return HealthReport(healthy=True, detail=UNVERIFIABLE_WEBHOOK)
        try:
            async with _slack_client(settings, settings.bot_token.get_secret_value()) as client:
                response = await client.post(SLACK_AUTH_TEST)
                answer = _slack_answer(response)
        # Broad on purpose: a health check reports a failure, it never raises one at the caller.
        except Exception as error:
            return HealthReport(healthy=False, detail=f"{type(error).__name__}: {error}")
        if not answer.ok:
            return HealthReport(healthy=False, detail=f"slack refused the token: {answer.error}")
        return HealthReport(healthy=True, detail=f"authenticated to {answer.team}" if answer.team else "token accepted")


#: What the check says about the webhook form, which nothing but a real post can prove.
UNVERIFIABLE_WEBHOOK = (
    "not verified: a Slack incoming webhook can only be checked by posting to it, which would "
    "put a message in the channel. Send a real one with `dg alerts test`."
)


def slack_body(message: AlertMessage) -> dict[str, object]:
    """Render an alert as the message body both Slack doors take.

    ``text`` is the fallback Slack shows where blocks do not render -- a notification, a
    screen reader, an old client -- so it carries the subject rather than being left out.
    """
    blocks: list[dict[str, object]] = [
        {"type": "header", "text": {"type": "plain_text", "text": _clip(message.subject, SLACK_HEADER_LIMIT)}},
        {"type": "section", "text": {"type": "mrkdwn", "text": _clip(message.body, SLACK_TEXT_LIMIT)}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": _slack_context(message)}]},
    ]
    if message.url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {"type": "button", "text": {"type": "plain_text", "text": "Open the run"}, "url": message.url}
                ],
            }
        )
    return {"text": message.subject, "blocks": blocks}


def _slack_context(message: AlertMessage) -> str:
    """Render the line under the alert: the pipeline in code formatting, and the event."""
    line = f"`{message.pipeline}` | {message.event}" if message.pipeline else message.event
    return _clip(line, SLACK_TEXT_LIMIT)


def _clip(text: str, limit: int) -> str:
    """Cut text to what a Slack block accepts, because an over-long one is refused whole."""
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _slack_client(settings: SlackNotifierConfig, token: str | None) -> httpx2.AsyncClient:
    """Open a client for one Slack call, presenting the bot token when there is one."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx2.AsyncClient(timeout=settings.timeout.total_seconds(), verify=settings.verify_tls, headers=headers)


async def _post_slack(settings: SlackNotifierConfig, url: str, body: dict[str, object], *, token: str | None) -> None:
    """Post one message and raise what Slack refused it with, in either of its two dialects."""
    async with _slack_client(settings, token) as client:
        response = await client.post(url, json=body)
    if response.status_code >= FAILED_STATUS:
        raise httpx2.HTTPStatusError(
            f"slack answered HTTP {response.status_code}",
            request=response.request,
            response=response,
        )
    # An incoming webhook answers `ok` as plain text; only the API form answers a document.
    if token is None:
        return
    answer = _slack_answer(response)
    if not answer.ok:
        raise SlackError(f"slack refused the message: {answer.error}")


class SlackAnswer(BaseModel):
    """What the Slack API says about a call, which it answers HTTP 200 for either way."""

    model_config = ConfigDict(extra="ignore")

    ok: bool = False
    error: str = "unknown"
    team: str | None = None


def _slack_answer(response: httpx2.Response) -> SlackAnswer:
    """Read a Slack API response, which answers HTTP 200 whether or not the call worked."""
    try:
        return SlackAnswer.model_validate(response.json())
    except ValidationError as error:
        raise SlackError(f"slack answered something that is not a result: {error}") from error


class EmailNotifierConfig(BlockModel):
    """The submission server an alert is mailed through, and who it goes to."""

    host: str = Field(default="", description="The SMTP server alerts are submitted to.")
    """Where the mail is handed over; a connection supplies this."""

    port: int = Field(default=587, gt=0, le=65535)
    """The submission port: 587 with STARTTLS, or 465 with implicit TLS."""

    security: Literal["starttls", "tls", "none"] = "starttls"
    """How the session is encrypted: STARTTLS on a plain port, implicit TLS, or nothing."""

    username: str | None = None
    """The submission account, where the server asks for one."""

    password: SecretStr | None = None
    """The submission account's password."""

    from_address: str = ""
    """The sender every alert is mailed from."""

    to: list[str] = Field(default_factory=list[str])
    """Who receives the alert; one message is sent to all of them."""

    subject_prefix: str = "[dirigent]"
    """Written before the alert's subject, so a mail rule can file alerts on sight."""

    timeout: Duration = Field(default=DEFAULT_TIMEOUT, gt=timedelta(0))
    """How long the submission may take before the delivery is retried."""


class EmailNotifier(Notifier):
    """Mails an alert, one plain-text message per alert."""

    id: ClassVar[str] = "email"
    config_model: ClassVar[type[BaseModel]] = EmailNotifierConfig

    async def send(self, message: AlertMessage, config: BaseModel) -> None:
        """Submit one alert as mail, raising so the queue retries a refusal.

        Raising rather than swallowing is the contract: the notification row owns the retry
        budget and the backoff, so a notifier that quietly returned on a refused submission
        would turn a recoverable blip into an alert nobody ever gets.
        """
        settings = EmailNotifierConfig.model_validate(config.model_dump())
        missing = _missing_email_settings(settings)
        if missing:
            raise ValueError(
                f"the email notifier has no {missing}; set it on the connection this rule delivers through"
            )
        use_tls, start_tls = _tls_modes(settings)
        await aiosmtplib.send(
            mail_of(settings, message),
            hostname=settings.host,
            port=settings.port,
            use_tls=use_tls,
            start_tls=start_tls,
            timeout=settings.timeout.total_seconds(),
            username=settings.username,
            password=_password(settings) if settings.username is not None else None,
        )


class EmailConnectionKind(ConnectionKind):
    """The credential record the email channel delivers through."""

    id: ClassVar[str] = "email"
    config_model: ClassVar[type[BaseModel]] = EmailNotifierConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Connect, greet, and log in where there are credentials, sending no message."""
        settings = EmailNotifierConfig.model_validate(config.model_dump())
        if not settings.host:
            return HealthReport(healthy=False, detail="no host is configured")
        use_tls, start_tls = _tls_modes(settings)
        try:
            async with aiosmtplib.SMTP(
                hostname=settings.host,
                port=settings.port,
                use_tls=use_tls,
                start_tls=start_tls,
                timeout=settings.timeout.total_seconds(),
            ) as client:
                greeting = await client.ehlo()
                if settings.username is not None:
                    await client.login(settings.username, _password(settings))
        # Broad on purpose: a health check reports a failure, it never raises one at the caller.
        except Exception as error:
            return HealthReport(healthy=False, detail=f"{type(error).__name__}: {error}")
        first = greeting.message.splitlines()[0] if greeting.message else ""
        stage = "authenticated" if settings.username is not None else "greeted"
        return HealthReport(healthy=True, detail=f"{stage}: {first}" if first else stage)


def _missing_email_settings(settings: EmailNotifierConfig) -> str:
    """Name the settings a submission cannot be made without, or nothing when it can."""
    absent = [
        name
        for name, value in (("host", settings.host), ("from_address", settings.from_address), ("to", settings.to))
        if not value
    ]
    return ", ".join(absent)


def mail_of(settings: EmailNotifierConfig, message: AlertMessage) -> EmailMessage:
    """Render an alert as the one plain-text message that is mailed for it."""
    mail = EmailMessage()
    mail["Subject"] = f"{settings.subject_prefix} {message.subject}".strip()
    mail["From"] = settings.from_address
    mail["To"] = ", ".join(settings.to)
    mail.set_content(mail_body(message))
    return mail


def mail_body(message: AlertMessage) -> str:
    """Render the plain-text body: the alert, then the facts under it."""
    lines = [
        message.subject,
        "",
        message.body,
        "",
        f"pipeline: {message.pipeline}" if message.pipeline else "pipeline: -",
        f"event: {message.event}",
    ]
    if message.url:
        lines.append(f"url: {message.url}")
    return "\n".join(lines) + "\n"


def _tls_modes(settings: EmailNotifierConfig) -> tuple[bool, bool]:
    """Render a security mode as the implicit-TLS and STARTTLS flags a session is opened with.

    ``start_tls`` is stated rather than left to negotiate, so a server that does not offer
    STARTTLS to a session configured for it is a refusal rather than a plaintext submission.
    """
    return settings.security == "tls", settings.security == "starttls"


def _password(settings: EmailNotifierConfig) -> str:
    """Open the submission password, which an account may legitimately have none for."""
    return settings.password.get_secret_value() if settings.password is not None else ""
