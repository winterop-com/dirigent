"""A caller held for its run's reply: what it is answered with, and what its journal row says."""

import asyncio
import time
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from dirigent_client.schemas import Page, SourceInputOut
from dirigent_core.config import Settings
from dirigent_core.engine.definition import ReplyNode
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.references import ReferenceScope
from dirigent_core.engine.replies import _rendered_headers, _Unrenderable  # pyright: ignore[reportPrivateUsage]
from dirigent_core.engine.services import EngineServices
from dirigent_server import create_app
from tests_support import apply_document

PREFIX = "/api/v1"

#: A public source, a step a worker has to run, and a reply answering from it.
WORKED = """
format: dirigent/v1
kind: pipeline
code: worked
steps:
  ask:
    source:
      kind: endpoint
      path: /worked
      auth: {{kind: public}}
  shape:
    block: transform.jq
    depends_on: [ask]
    config:
      input: ${{steps.ask.output.body}}
      program: '{{doubled: (.n * 2)}}'
  answer:
    depends_on: [shape]
    reply:
{reply}
"""


def worked(reply: str = "      body: ${steps.shape.output.value}") -> str:
    """Write the worked document with its reply's fields."""
    return WORKED.format(reply=reply)


def answered_at_once(reply: str, path: str = "/now") -> str:
    """Write a public source answered by a reply with nothing between them."""
    return f"""
format: dirigent/v1
kind: pipeline
code: now
steps:
  ask:
    source:
      kind: endpoint
      path: {path}
      auth: {{kind: public}}
  answer:
    depends_on: [ask]
    reply:
{reply}
"""


def inputs(client: TestClient, pipeline: str) -> list[SourceInputOut]:
    """Read a source's journal, newest first."""
    response = client.get(f"{PREFIX}/pipelines/{pipeline}/sources/ask/inputs")
    assert response.status_code == 200, response.text
    return Page[SourceInputOut].model_validate(response.json()).items


def held_until_accepted(client: TestClient, pool: ThreadPoolExecutor, pipeline: str, body: Any) -> "Future[Any]":
    """Send a call from another thread, and return once its run exists and the caller is held."""
    sent = pool.submit(lambda: client.post(f"/endpoints/{pipeline}", json=body, headers={"Authorization": ""}))
    deadline = time.monotonic() + 10
    while not inputs(client, pipeline):
        assert time.monotonic() < deadline, "the call never became a run"
        assert not sent.done(), sent.result().text
        time.sleep(0.02)
    return sent


def work_one(client: TestClient) -> None:
    """Claim and run one unit of work, as a worker would."""
    app = cast("FastAPI", client.app)
    engine = Engine(app.state.session_factory, cast("EngineServices", app.state.services), owner="test-worker")

    async def once() -> None:
        unit = await engine.claim()
        assert unit is not None, "nothing was queued"
        await engine.run_unit(unit)

    assert client.portal is not None
    client.portal.call(once)


def test_a_reply_answers_with_the_status_headers_and_text_it_renders(client: TestClient) -> None:
    apply_document(
        client,
        answered_at_once(
            """      status: 201
      content_type: text/plain
      headers: {x-greeting: "hello ${steps.ask.output.body.who}"}
      body: "made ${steps.ask.output.body.who}"
""",
        ),
    )
    called = client.post("/endpoints/now", json={"who": "ann"}, headers={"Authorization": ""})
    assert called.status_code == 201, called.text
    assert called.headers["x-greeting"] == "hello ann"
    assert called.headers["content-type"].startswith("text/plain")
    assert called.text == "made ann"
    [entry] = inputs(client, "now")
    assert (entry.outcome, entry.status) == ("replied", 201)


def test_a_reply_streams_the_stored_object_its_body_from_names(client: TestClient, settings: Settings) -> None:
    stored = Path(settings.artifact_root.removeprefix("file://")) / "replies" / "greeting.txt"
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_text("stored hello")
    apply_document(client, answered_at_once(f"      content_type: text/plain\n      body_from: file://{stored}\n"))
    called = client.post("/endpoints/now", json={}, headers={"Authorization": ""})
    assert called.status_code == 200, called.text
    assert called.text == "stored hello"
    assert called.headers["content-security-policy"].startswith("sandbox;")
    assert called.headers["x-content-type-options"] == "nosniff"


def test_a_reply_that_cannot_render_answers_422_naming_the_run(client: TestClient) -> None:
    apply_document(client, answered_at_once("      status: ${steps.ask.output.body.status}\n"))
    called = client.post("/endpoints/now", json={"status": "not a status"}, headers={"Authorization": ""})
    assert called.status_code == 422, called.text
    problem = called.json()
    assert problem["code"] == "source.reply_rejected"
    [entry] = inputs(client, "now")
    assert problem["params"]["run"] == str(entry.run_id)
    assert called.headers["location"] == f"{PREFIX}/runs/{entry.run_id}"
    assert (entry.outcome, entry.status) == ("replied", 422)


@pytest.mark.parametrize(
    ("reply", "said"),
    [
        ("      status: ${steps.ask.output.body.value}\n", "\u00b2"),
        ("      status: ${steps.ask.output.body.value}\n", "9" * 5000),
        ("      body_from: ${steps.ask.output.body.value}\n", "file:///etc/hostname"),
        ("      body_from: ${steps.ask.output.body.value}\n", "nosuchscheme://bucket/key"),
        ("      body_from: ${steps.ask.output.body.value}\n", "file:///tmp/\u0000"),
        ('      content_type: "text/plain; charset=ascii"\n      body: ${steps.ask.output.body.value}\n', "bl\u00e5"),
        ('      content_type: "text/plain; charset=nope"\n      body: ${steps.ask.output.body.value}\n', "text"),
    ],
)
def test_anything_a_reply_cannot_render_settles_it_as_rejected(client: TestClient, reply: str, said: str) -> None:
    apply_document(client, answered_at_once(reply))
    called = client.post("/endpoints/now", json={"value": said}, headers={"Authorization": ""})
    assert called.status_code == 422, called.text
    assert called.json()["code"] == "source.reply_rejected"
    assert "artifacts" not in called.text, "the caller is not told where the instance keeps its artifacts"


@pytest.mark.parametrize("status", ["²", "9" * 5000])
async def test_a_reply_that_cannot_render_after_a_worker_step_ends_the_run_with_that_step_run_once(
    settings: Settings, admin_token: str, status: str
) -> None:
    document = """
format: dirigent/v1
kind: pipeline
code: after-work
steps:
  ask:
    source:
      kind: endpoint
      path: /after-work
      auth: {kind: public}
  work:
    block: transform.jq
    depends_on: [ask]
    config:
      input: ${steps.ask.output.body}
      program: '.'
  answer:
    depends_on: [work]
    reply:
      status: ${steps.ask.output.body.status}
"""
    app = create_app(settings, scheduler=False)
    admin = {"Authorization": f"Bearer {admin_token}"}
    async with (
        app.router.lifespan_context(app),
        httpx2.AsyncClient(transport=httpx2.ASGITransport(app), base_url="http://testserver") as client,
    ):
        applied = await client.post(
            f"{PREFIX}/pipelines/$apply",
            json={"document": yaml.safe_load(document), "paused": False},
            headers=admin,
        )
        assert applied.status_code == 200, applied.text
        held = asyncio.create_task(client.post("/endpoints/after-work", json={"status": status}))
        engine = Engine(app.state.session_factory, app.state.services, owner="worker")
        async with asyncio.timeout(10):
            while (unit := await engine.claim()) is None:
                await asyncio.sleep(0.02)
        await engine.run_unit(unit)
        called = await asyncio.wait_for(held, timeout=10)
        assert called.status_code == 422, called.text
        assert await engine.claim() is None, "nothing is left to run"
        run_id = called.json()["params"]["run"]
        attempts = (await client.get(f"{PREFIX}/runs/{run_id}/attempts", headers=admin)).json()["items"]
        assert [(row["step_name"], row["status"]) for row in attempts if row["step_name"] == "work"] == [
            ("work", "succeeded")
        ]
        assert (await client.get(f"{PREFIX}/runs/{run_id}", headers=admin)).json()["run"]["status"] == "failed"


@pytest.mark.parametrize(
    "header",
    [
        "Set-Cookie",
        "WWW-Authenticate",
        "Refresh",
        "Clear-Site-Data",
        "Content-Security-Policy",
        "X-Content-Type-Options",
        "X-Frame-Options",
        "Strict-Transport-Security",
        "Cross-Origin-Opener-Policy",
        "X-Accel-Redirect",
        "Transfer-Encoding",
    ],
)
def test_a_header_a_reply_may_not_set_is_refused_at_apply(header: str) -> None:
    with pytest.raises(ValidationError, match="does not set"):
        ReplyNode(headers={header: "x"})


def test_a_header_a_reply_may_not_set_is_refused_at_render() -> None:
    with pytest.raises(_Unrenderable) as raised:
        _rendered_headers("answer", {"Set-Cookie": "session=x"}, ReferenceScope())
    assert raised.value.failure.code == "run.reply_refused"


def test_a_reply_may_still_set_an_ordinary_header() -> None:
    node = ReplyNode(headers={"Location": "/elsewhere", "X-Greeting": "hello", "Content-Disposition": "attachment"})
    assert _rendered_headers("answer", node.headers, ReferenceScope()) == {
        "location": "/elsewhere",
        "x-greeting": "hello",
        "content-disposition": "attachment",
    }


def test_a_header_value_a_reference_resolves_to_cannot_start_another_header(client: TestClient) -> None:
    apply_document(client, answered_at_once('      headers: {x-greeting: "${steps.ask.output.body.who}"}\n'))
    called = client.post("/endpoints/now", json={"who": "ann\r\nSet-Cookie: session=x"}, headers={"Authorization": ""})
    assert called.status_code == 422, called.text
    assert "set-cookie" not in called.headers


def test_an_html_reply_is_inert(client: TestClient) -> None:
    apply_document(
        client,
        answered_at_once(
            """      content_type: text/html
      body: "<script>${steps.ask.output.body.who}</script>"
"""
        ),
    )
    called = client.post("/endpoints/now", json={"who": "alert(1)"}, headers={"Authorization": ""})
    assert called.status_code == 200, called.text
    assert called.headers["content-type"].startswith("text/html")
    assert called.headers["content-security-policy"].startswith("sandbox;")
    assert called.headers["x-content-type-options"] == "nosniff"


def test_a_bodyless_reply_is_contained_too(client: TestClient) -> None:
    apply_document(client, answered_at_once("      status: 204\n"))
    called = client.post("/endpoints/now", json={}, headers={"Authorization": ""})
    assert called.status_code == 204, called.text
    assert called.headers["content-security-policy"].startswith("sandbox;")


def test_a_caller_is_held_while_a_worker_runs_the_steps_its_reply_answers_from(client: TestClient) -> None:
    apply_document(client, worked())
    with ThreadPoolExecutor(1) as pool:
        sent = held_until_accepted(client, pool, "worked", {"n": 21})
        assert not sent.done(), "the caller waits for the reply"
        work_one(client)
        called = sent.result(timeout=10)
    assert called.status_code == 200, called.text
    assert called.json() == {"doubled": 42}
    [entry] = inputs(client, "worked")
    assert (entry.outcome, entry.status) == ("replied", 200)


def test_a_run_settled_with_no_reply_answers_502(client: TestClient) -> None:
    apply_document(client, worked())
    with ThreadPoolExecutor(1) as pool:
        sent = held_until_accepted(client, pool, "worked", {"n": 1})
        run_id = inputs(client, "worked")[0].run_id
        assert client.post(f"{PREFIX}/runs/{run_id}/$cancel").status_code == 200
        called = sent.result(timeout=10)
    assert called.status_code == 502, called.text
    assert called.json()["code"] == "source.reply_unanswered"
    assert called.json()["params"] == {"run": str(run_id), "status": "cancelled"}


def test_a_caller_past_its_timeout_is_answered_504_and_the_run_carries_on(client: TestClient) -> None:
    apply_document(client, worked("      timeout: 200ms\n      body: ${steps.shape.output.value}"))
    called = client.post("/endpoints/worked", json={"n": 1}, headers={"Authorization": ""})
    assert called.status_code == 504, called.text
    assert called.json()["code"] == "source.reply_timed_out"
    [entry] = inputs(client, "worked")
    assert (entry.outcome, entry.status) == ("timed_out", 504)
    run = client.get(f"{PREFIX}/runs/{entry.run_id}").json()["run"]
    assert run["status"] in {"queued", "running"}, "the run is not cancelled by the caller leaving"


def test_a_server_holding_as_many_callers_as_it_may_refuses_the_next_503(settings: Settings, admin_token: str) -> None:
    narrow = settings.model_copy(update={"source_max_waiting": 1})
    with TestClient(create_app(narrow), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        apply_document(client, worked())
        with ThreadPoolExecutor(1) as pool:
            sent = held_until_accepted(client, pool, "worked", {"n": 1})
            refused = client.post("/endpoints/worked", json={"n": 2}, headers={"Authorization": ""})
            assert refused.status_code == 503, refused.text
            assert refused.json()["code"] == "source.waiting_full"
            work_one(client)
            assert sent.result(timeout=10).status_code == 200
        assert [entry.outcome for entry in inputs(client, "worked")] == ["refused", "replied"]


def test_one_source_holds_no_more_than_its_share_and_leaves_the_rest_for_others(
    settings: Settings, admin_token: str
) -> None:
    narrow = settings.model_copy(update={"source_max_waiting_per_source": 1})
    with TestClient(create_app(narrow), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        apply_document(client, worked())
        apply_document(client, answered_at_once("      body: ${steps.ask.output.body}\n"))
        with ThreadPoolExecutor(1) as pool:
            sent = held_until_accepted(client, pool, "worked", {"n": 1})
            refused = client.post("/endpoints/worked", json={"n": 2}, headers={"Authorization": ""})
            assert refused.status_code == 503, refused.text
            assert refused.json()["code"] == "source.waiting_share"
            other = client.post("/endpoints/now", json={"ok": True}, headers={"Authorization": ""})
            assert other.status_code == 200, "another source still has its seats"
            work_one(client)
            assert sent.result(timeout=10).status_code == 200
