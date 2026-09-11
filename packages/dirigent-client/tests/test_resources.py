"""Every namespaced accessor: the method it uses, the path it addresses, and what it sends."""

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import httpx2
import pytest

from clientsupport import Recorder, client_of
from dirigent_client import (
    API_PREFIX,
    AlertEvent,
    AlertScope,
    BlockKind,
    Dirigent,
    RunStatus,
    UserRole,
)

ID = "0193b0f0-0000-7000-8000-000000000001"
WHEN = "2026-01-01T00:00:00+00:00"

PIPELINE = {
    "id": ID,
    "code": "demo",
    "active": True,
    "current_version": 3,
    "active_runs": 0,
    "created_at": WHEN,
    "updated_at": WHEN,
}
RUN = {
    "id": ID,
    "pipeline": "demo",
    "pipeline_version": 3,
    "status": "succeeded",
    "triggered_by_kind": "adhoc",
    "created_at": WHEN,
}
ATTEMPT = {
    "id": ID,
    "step_name": "greet",
    "block_id": "shell.run",
    "attempt": 1,
    "kind": "manual",
    "status": "queued",
}
SCHEDULE = {
    "id": ID,
    "code": "nightly",
    "kind": "cron",
    "cron": "0 5 * * *",
    "timezone": "UTC",
    "paused": False,
    "managed": False,
    "created_at": WHEN,
}
WEBHOOK = {
    "id": ID,
    "code": "inbound",
    "token_prefix": "dgw_abc",
    "signed": False,
    "active": True,
    "managed": False,
    "rate_limit_per_minute": 60,
    "created_at": WHEN,
}
WEBHOOK_TOKEN = {
    "webhook_id": ID,
    "code": "inbound",
    "token": "dgw_abc123",
    "prefix": "dgw_abc",
    "url_path": "/hooks/x",
}
CONNECTION = {
    "id": ID,
    "code": "warehouse",
    "kind": "http",
    "config": {"base_url": "https://example.org"},
    "created_at": WHEN,
    "updated_at": WHEN,
}
EXAMPLE = {
    "code": "open-meteo-weekly-report",
    "name": "Weekly weather report",
    "tags": ["open-data", "starter"],
    "requires": {"blocks": ["http.request"]},
    "plugin": "examples",
    "shelf": "open-data",
    "starter": True,
}
USER = {"id": ID, "username": "tester", "role": "admin", "active": True, "created_at": WHEN}
ALERT_RULE = {
    "id": ID,
    "code": "on-failure",
    "event": "run_failed",
    "scope": "global",
    "notifier": "log",
    "throttle": "0s",
    "active": True,
    "created_at": WHEN,
}

PAYLOADS: dict[str, Any] = {
    "/pipelines": {"items": [PIPELINE], "next": None},
    "/pipelines/$apply": {"plan": {"code": "demo", "action": "create", "digest": "sha256:abc"}},
    "/pipelines/demo": {**PIPELINE, "document": {"steps": {}}},
    "/pipelines/demo/versions": {
        "items": [{"id": ID, "version": 3, "digest": "sha256:abc", "provenance_source": "file", "created_at": WHEN}],
        "next": None,
    },
    "/pipelines/demo/$activate": PIPELINE,
    "/pipelines/demo/$deactivate": PIPELINE,
    "/pipelines/demo/$run": {"run_id": ID, "status": "queued"},
    "/runs": {"items": [RUN], "next": None},
    f"/runs/{ID}": {"run": RUN, "items": [], "attempts": [], "dag": {"nodes": [], "edges": []}},
    f"/runs/{ID}/$cancel": RUN,
    f"/runs/{ID}/$logs": {"items": [], "next": None},
    f"/runs/{ID}/$report": {
        "run_id": ID,
        "pipeline": "demo",
        "pipeline_version": 3,
        "status": "succeeded",
        "steps": [],
    },
    f"/attempts/{ID}/$retry": ATTEMPT,
    "/connections": {"items": [CONNECTION], "next": None},
    "/connections/warehouse": CONNECTION,
    "/connections/warehouse/$check": {"healthy": True, "detail": "200 OK"},
    "/blocks": {"api_version": 1, "blocks": []},
    "/examples": {"items": [EXAMPLE], "next": None},
    "/examples/open-meteo-weekly-report": {**EXAMPLE, "source": "format: dirigent/v1\n", "path": "open-data/x.yaml"},
    "/blocks/shell.run": {
        "id": "shell.run",
        "kind": "operator",
        "summary": "Run a command.",
        "group": "execute",
        "plugin": "builtin",
    },
    "/pipelines/demo/triggers/schedules": {"items": [SCHEDULE], "next": None},
    "/pipelines/demo/triggers/schedules/nightly": SCHEDULE,
    "/pipelines/demo/triggers/schedules/nightly/$pause": SCHEDULE,
    "/pipelines/demo/triggers/schedules/nightly/$resume": SCHEDULE,
    "/pipelines/demo/triggers/schedules/nightly/firings": {
        "items": [{"id": 1, "scheduled_for": WHEN, "created_at": WHEN, "outcome": "fired", "misfired": False}],
        "next": None,
    },
    "/pipelines/demo/triggers/webhooks": {"items": [WEBHOOK], "next": None},
    "/pipelines/demo/triggers/webhooks/inbound": WEBHOOK,
    "/pipelines/demo/triggers/webhooks/inbound/$rotate-token": WEBHOOK_TOKEN,
    "/pipelines/demo/triggers/webhooks/inbound/$enable": WEBHOOK,
    "/pipelines/demo/triggers/webhooks/inbound/$disable": WEBHOOK,
    "/pipelines/demo/triggers/webhooks/inbound/deliveries": {
        "items": [{"id": 1, "created_at": WHEN, "outcome": "accepted"}],
        "next": None,
    },
    "/alert-rules": {"items": [ALERT_RULE], "next": None},
    "/alert-rules/on-failure": ALERT_RULE,
    "/alert-rules/$test": {"notification_id": ID, "notifier": "log"},
    "/notifications": {
        "items": [
            {
                "id": ID,
                "event": "run_failed",
                "notifier": "log",
                "subject": "a run failed",
                "status": "pending",
                "attempt": 0,
                "max_attempts": 5,
                "available_at": WHEN,
                "created_at": WHEN,
            }
        ],
        "next": None,
    },
    f"/notifications/{ID}/$retry": {
        "id": ID,
        "event": "run_failed",
        "notifier": "log",
        "subject": "a run failed",
        "status": "pending",
        "attempt": 0,
        "max_attempts": 5,
        "available_at": WHEN,
        "created_at": WHEN,
    },
    f"/notifications/{ID}": {
        "id": ID,
        "event": "run_failed",
        "notifier": "log",
        "subject": "a run failed",
        "status": "pending",
        "attempt": 0,
        "max_attempts": 5,
        "available_at": WHEN,
        "created_at": WHEN,
    },
    "/system/info": {
        "version": "0.1.0",
        "environment": "dev",
        "database": "sqlite",
        "checked_at": WHEN,
    },
    "/workers": {
        "items": [
            {
                "id": ID,
                "name": "worker-1",
                "hostname": "box",
                "version": "0.1.0",
                "status": "running",
                "concurrency": 4,
                "created_at": WHEN,
                "last_seen_at": WHEN,
            }
        ],
        "next": None,
    },
    "/auth/login": {"user_id": ID, "username": "tester", "role": "admin"},
    "/auth/me": {"user_id": ID, "username": "tester", "role": "admin"},
    "/users": {"items": [USER], "next": None},
    "/users/second": USER,
    "/users/second/$reset-password": None,
    "/health": {"status": "ok", "version": "0.1.0"},
    "/health/ready": {"status": "healthy", "checks": {"database": {"status": "healthy"}}},
}

CREATED: dict[str, Any] = {
    "/connections": CONNECTION,
    "/pipelines/demo/triggers/schedules": SCHEDULE,
    "/pipelines/demo/triggers/webhooks": WEBHOOK_TOKEN,
    "/alert-rules": ALERT_RULE,
    "/users": USER,
    "/tokens": {"id": ID, "name": "ci", "username": "tester", "prefix": "dgt_abc", "token": "dgt_abc123"},
    "/users/second/tokens": {
        "id": ID,
        "name": "ci",
        "username": "second",
        "prefix": "dgt_abc",
        "token": "dgt_abc123",
    },
}

LISTED_TOKENS = {
    "items": [{"id": ID, "name": "ci", "username": "tester", "prefix": "dgt_abc", "created_at": WHEN}],
    "next": None,
}

ACCESSORS: list[tuple[str, Callable[[Dirigent], Awaitable[object]], str, str]] = [
    ("pipelines.list", lambda dg: dg.pipelines.list(), "GET", "/pipelines"),
    ("pipelines.apply", lambda dg: dg.pipelines.apply({"code": "demo"}), "POST", "/pipelines/$apply"),
    ("pipelines.get", lambda dg: dg.pipelines.get("demo"), "GET", "/pipelines/demo"),
    ("pipelines.versions", lambda dg: dg.pipelines.versions("demo"), "GET", "/pipelines/demo/versions"),
    ("pipelines.export", lambda dg: dg.pipelines.export("demo"), "GET", "/pipelines/demo/$export"),
    ("pipelines.activate", lambda dg: dg.pipelines.activate("demo"), "POST", "/pipelines/demo/$activate"),
    ("pipelines.deactivate", lambda dg: dg.pipelines.deactivate("demo"), "POST", "/pipelines/demo/$deactivate"),
    ("pipelines.delete", lambda dg: dg.pipelines.delete("demo"), "DELETE", "/pipelines/demo"),
    ("pipelines.run", lambda dg: dg.pipelines.run("demo", params={"day": "1"}), "POST", "/pipelines/demo/$run"),
    ("runs.list", lambda dg: dg.runs.list(status=RunStatus.FAILED, since="24h"), "GET", "/runs"),
    ("runs.get", lambda dg: dg.runs.get(ID), "GET", f"/runs/{ID}"),
    ("runs.cancel", lambda dg: dg.runs.cancel(ID), "POST", f"/runs/{ID}/$cancel"),
    ("runs.retry", lambda dg: dg.runs.retry(ID), "POST", f"/attempts/{ID}/$retry"),
    ("runs.logs", lambda dg: dg.runs.logs(ID), "GET", f"/runs/{ID}/$logs"),
    ("runs.report", lambda dg: dg.runs.report(ID), "GET", f"/runs/{ID}/$report"),
    ("connections.list", lambda dg: dg.connections.list(), "GET", "/connections"),
    ("connections.get", lambda dg: dg.connections.get("warehouse"), "GET", "/connections/warehouse"),
    ("connections.create", lambda dg: dg.connections.create("warehouse", kind="http"), "POST", "/connections"),
    ("connections.update", lambda dg: dg.connections.update("warehouse", config={}), "PATCH", "/connections/warehouse"),
    ("connections.delete", lambda dg: dg.connections.delete("warehouse"), "DELETE", "/connections/warehouse"),
    ("connections.check", lambda dg: dg.connections.check("warehouse"), "POST", "/connections/warehouse/$check"),
    (
        "examples.list",
        lambda dg: dg.examples.list(tags=["starter"], shelf="open-data", starter=True),
        "GET",
        "/examples",
    ),
    (
        "examples.get",
        lambda dg: dg.examples.get("open-meteo-weekly-report"),
        "GET",
        "/examples/open-meteo-weekly-report",
    ),
    ("blocks.catalog", lambda dg: dg.blocks.catalog(kind=BlockKind.SENSOR), "GET", "/blocks"),
    ("blocks.get", lambda dg: dg.blocks.get("shell.run"), "GET", "/blocks/shell.run"),
    ("schedules.list", lambda dg: dg.schedules.list("demo"), "GET", "/pipelines/demo/triggers/schedules"),
    (
        "schedules.get",
        lambda dg: dg.schedules.get("demo", "nightly"),
        "GET",
        "/pipelines/demo/triggers/schedules/nightly",
    ),
    (
        "schedules.create",
        lambda dg: dg.schedules.create("demo", "nightly", cron="0 5 * * *"),
        "POST",
        "/pipelines/demo/triggers/schedules",
    ),
    (
        "schedules.update",
        lambda dg: dg.schedules.update("demo", "nightly", interval="1h"),
        "PATCH",
        "/pipelines/demo/triggers/schedules/nightly",
    ),
    (
        "schedules.pause",
        lambda dg: dg.schedules.pause("demo", "nightly"),
        "POST",
        "/pipelines/demo/triggers/schedules/nightly/$pause",
    ),
    (
        "schedules.resume",
        lambda dg: dg.schedules.resume("demo", "nightly"),
        "POST",
        "/pipelines/demo/triggers/schedules/nightly/$resume",
    ),
    (
        "schedules.firings",
        lambda dg: dg.schedules.firings("demo", "nightly"),
        "GET",
        "/pipelines/demo/triggers/schedules/nightly/firings",
    ),
    (
        "schedules.delete",
        lambda dg: dg.schedules.delete("demo", "nightly"),
        "DELETE",
        "/pipelines/demo/triggers/schedules/nightly",
    ),
    ("webhooks.list", lambda dg: dg.webhooks.list("demo"), "GET", "/pipelines/demo/triggers/webhooks"),
    (
        "webhooks.get",
        lambda dg: dg.webhooks.get("demo", "inbound"),
        "GET",
        "/pipelines/demo/triggers/webhooks/inbound",
    ),
    (
        "webhooks.create",
        lambda dg: dg.webhooks.create("demo", "inbound", hmac_secret="shh"),
        "POST",
        "/pipelines/demo/triggers/webhooks",
    ),
    (
        "webhooks.rotate_token",
        lambda dg: dg.webhooks.rotate_token("demo", "inbound"),
        "POST",
        "/pipelines/demo/triggers/webhooks/inbound/$rotate-token",
    ),
    (
        "webhooks.enable",
        lambda dg: dg.webhooks.enable("demo", "inbound"),
        "POST",
        "/pipelines/demo/triggers/webhooks/inbound/$enable",
    ),
    (
        "webhooks.disable",
        lambda dg: dg.webhooks.disable("demo", "inbound"),
        "POST",
        "/pipelines/demo/triggers/webhooks/inbound/$disable",
    ),
    (
        "webhooks.deliveries",
        lambda dg: dg.webhooks.deliveries("demo", "inbound"),
        "GET",
        "/pipelines/demo/triggers/webhooks/inbound/deliveries",
    ),
    (
        "webhooks.delete",
        lambda dg: dg.webhooks.delete("demo", "inbound"),
        "DELETE",
        "/pipelines/demo/triggers/webhooks/inbound",
    ),
    ("alerts.rules", lambda dg: dg.alerts.rules(), "GET", "/alert-rules"),
    (
        "alerts.create_rule",
        lambda dg: dg.alerts.create_rule(
            "on-failure",
            event=AlertEvent.RUN_FAILED,
            notifier="log",
            scope=AlertScope.GLOBAL,
            throttle=timedelta(minutes=15),
        ),
        "POST",
        "/alert-rules",
    ),
    ("alerts.delete_rule", lambda dg: dg.alerts.delete_rule("on-failure"), "DELETE", "/alert-rules/on-failure"),
    (
        "alerts.test",
        lambda dg: dg.alerts.test(notifier="log", subject="hi", body="there"),
        "POST",
        "/alert-rules/$test",
    ),
    ("alerts.notifications", lambda dg: dg.alerts.notifications(run_id=ID), "GET", "/notifications"),
    ("alerts.notification", lambda dg: dg.alerts.notification(ID), "GET", f"/notifications/{ID}"),
    ("alerts.retry", lambda dg: dg.alerts.retry(ID), "POST", f"/notifications/{ID}/$retry"),
    (
        "alerts.set_rule_paused",
        lambda dg: dg.alerts.set_rule_paused("on-failure", paused=True),
        "PATCH",
        "/alert-rules/on-failure",
    ),
    ("system.info", lambda dg: dg.system.info(), "GET", "/system/info"),
    ("workers.list", lambda dg: dg.workers.list(), "GET", "/workers"),
    ("auth.login", lambda dg: dg.auth.login("tester", "a password"), "POST", "/auth/login"),
    ("auth.logout", lambda dg: dg.auth.logout(), "POST", "/auth/logout"),
    ("auth.whoami", lambda dg: dg.auth.whoami(), "GET", "/auth/me"),
    ("admin.users.list", lambda dg: dg.admin.users.list(), "GET", "/users"),
    (
        "admin.users.create",
        lambda dg: dg.admin.users.create("new", "a password", role=UserRole.OPERATOR),
        "POST",
        "/users",
    ),
    (
        "admin.users.update",
        lambda dg: dg.admin.users.update("second", email="one@example.com"),
        "PATCH",
        "/users/second",
    ),
    (
        "admin.users.reset_password",
        lambda dg: dg.admin.users.reset_password("second", "a new password"),
        "POST",
        "/users/second/$reset-password",
    ),
    ("admin.users.tokens", lambda dg: dg.admin.users.tokens("second"), "GET", "/users/second/tokens"),
    (
        "admin.users.create_token",
        lambda dg: dg.admin.users.create_token("second", "ci"),
        "POST",
        "/users/second/tokens",
    ),
    (
        "admin.users.revoke_token",
        lambda dg: dg.admin.users.revoke_token("second", "ci"),
        "DELETE",
        "/users/second/tokens/ci",
    ),
    ("admin.tokens.create", lambda dg: dg.admin.tokens.create("ci"), "POST", "/tokens"),
    ("admin.tokens.revoke", lambda dg: dg.admin.tokens.revoke("ci"), "DELETE", "/tokens/ci"),
]


def _answer(request: httpx2.Request) -> httpx2.Response:
    """Serve the canned payload for whatever path was asked for."""
    path = request.url.path.removeprefix(API_PREFIX) or "/"
    if request.method == "DELETE" or path == "/auth/logout":
        return httpx2.Response(204, headers={"X-Dirigent-Version": "0.1.0"})
    if path == "/pipelines/demo/$export":
        return httpx2.Response(200, text="format: dirigent/v1\n", headers={"X-Dirigent-Version": "0.1.0"})
    if path in {"/tokens", "/users/second/tokens"} and request.method == "GET":
        return httpx2.Response(200, json=LISTED_TOKENS, headers={"X-Dirigent-Version": "0.1.0"})
    if request.method == "POST" and path in CREATED:
        return httpx2.Response(201, json=CREATED[path], headers={"X-Dirigent-Version": "0.1.0"})
    return httpx2.Response(200, json=PAYLOADS[path], headers={"X-Dirigent-Version": "0.1.0"})


@pytest.mark.parametrize(("name", "call", "method", "path"), ACCESSORS, ids=[row[0] for row in ACCESSORS])
async def test_each_accessor_addresses_the_endpoint_it_names(
    name: str, call: Callable[[Dirigent], Awaitable[object]], method: str, path: str
) -> None:
    recorder = Recorder(_answer)
    async with client_of(recorder) as dg:
        await call(dg)
    assert recorder.last[0] == method
    assert recorder.last[1] == f"{API_PREFIX}{path}"


async def test_the_token_listing_is_the_one_get_that_shares_a_path_with_a_post() -> None:
    recorder = Recorder(_answer)
    async with client_of(recorder) as dg:
        tokens = await dg.admin.tokens.list()
    assert [(token.username, token.name) for token in tokens.items] == [("tester", "ci")]


async def test_creating_an_account_names_a_role_or_does_not_compile() -> None:
    """The keyword has no default, so a caller cannot mint an admin by omission."""
    recorder = Recorder(_answer)
    async with client_of(recorder) as dg:
        with pytest.raises(TypeError):
            await dg.admin.users.create("new", "a password")  # type: ignore[call-arg]
    assert recorder.calls == []


async def test_the_probes_are_addressed_outside_the_versioned_api() -> None:
    recorder = Recorder(_answer)
    async with client_of(recorder) as dg:
        assert (await dg.system.health()).status == "ok"
        assert (await dg.system.ready()).status == "healthy"
    assert recorder.paths == ["/health", "/health/ready"]


async def test_an_unhealthy_readiness_probe_is_a_report_rather_than_an_exception() -> None:
    body = {"status": "unhealthy", "checks": {"database": {"status": "unhealthy", "detail": "unreachable"}}}
    answer = httpx2.Response(503, json=body, headers={"X-Dirigent-Version": "0.1.0"})
    async with client_of(Recorder([answer])) as dg:
        report = await dg.system.ready()
    assert report.status == "unhealthy"
    assert report.checks["database"].detail == "unreachable"


async def test_a_secret_travels_as_its_value_rather_than_as_its_mask() -> None:
    recorder = Recorder(_answer)
    async with client_of(recorder) as dg:
        await dg.auth.login("tester", "a password")
        assert recorder.last[3] == {"username": "tester", "password": "a password"}
        await dg.webhooks.create("demo", "inbound", hmac_secret="shh")
        assert recorder.last[3]["hmac_secret"] == "shh"
        await dg.admin.users.create("new", "another password", role=UserRole.ADMIN)
        assert recorder.last[3]["password"] == "another password"


async def test_only_the_arguments_a_caller_supplied_reach_the_query_string() -> None:
    recorder = Recorder(_answer)
    async with client_of(recorder) as dg:
        await dg.runs.list(pipeline="demo", limit=10)
    assert recorder.last[2] == "pipeline=demo&limit=10"


async def test_a_run_that_the_concurrency_policy_declined_is_not_an_error() -> None:
    body = {"run_id": None, "status": "skipped", "detail": "a run of this pipeline is already in flight"}
    async with client_of(Recorder([httpx2.Response(202, json=body, headers={"X-Dirigent-Version": "0.1.0"})])) as dg:
        accepted = await dg.pipelines.run("demo")
    assert accepted.run_id is None
    assert accepted.status == "skipped"


async def test_a_retry_sends_an_idempotency_key_so_a_repeat_creates_one_attempt() -> None:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(202, json=ATTEMPT, headers={"X-Dirigent-Version": "0.1.0"})

    async with client_of(Recorder(handler)) as dg:
        await dg.runs.retry(UUID(ID))
        await dg.runs.retry(UUID(ID), idempotency_key="mine")
    assert seen[0].headers["idempotency-key"]
    assert seen[1].headers["idempotency-key"] == "mine"


async def test_a_client_reaches_an_instance_that_moved_its_api() -> None:
    """A server that sets api_prefix serves the API somewhere else, and a client can follow.

    The setting is real and the server honours it, so a client that hardcoded the default
    left a valid configuration unreachable by its own SDK and CLI.
    """
    seen: list[str] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        return httpx2.Response(200, json={"items": [], "next": None})

    async with Dirigent(
        url="http://instance.test",
        api_prefix="/dirigent/v2",
        http_transport=httpx2.MockTransport(handler),
    ) as dg:
        await dg.pipelines.list()

    assert seen == ["/dirigent/v2/pipelines"]


async def test_a_prefix_is_spelled_the_way_the_server_spells_it() -> None:
    """The server normalises its own setting, so a hand-written one addresses the same place."""
    for written in ("api/v2", "/api/v2", "/api/v2/"):
        seen: list[str] = []

        def handler(request: httpx2.Request, seen: list[str] = seen) -> httpx2.Response:
            seen.append(request.url.path)
            return httpx2.Response(200, json={"items": [], "next": None})

        async with Dirigent(
            url="http://instance.test", api_prefix=written, http_transport=httpx2.MockTransport(handler)
        ) as dg:
            await dg.pipelines.list()

        assert seen == ["/api/v2/pipelines"], f"{written!r} addressed somewhere else"
