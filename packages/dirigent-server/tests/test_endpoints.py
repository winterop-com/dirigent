"""A call under /endpoints: each check in its order, what it answers, and what it writes down."""

from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from dirigent_client.schemas import AttemptOut, Page, SourceInputOut, SourceOut
from tests_support import apply_document

PREFIX = "/api/v1"

#: A source with a reply, whose runs the server settles without a worker.
ECHO = """
format: dirigent/v1
kind: pipeline
code: echo
steps:
  ask:
    source:
      kind: endpoint
      path: /echo/{{who}}
      methods: [POST, PUT]
{extra}
  answer:
    depends_on: [ask]
    reply:
      status: 200
      body: ${{steps.ask.output.body}}
"""

#: A source whose runs wait on a worker, so they stay in flight for as long as a test needs.
HELD = """
format: dirigent/v1
kind: pipeline
code: held
{concurrency}
steps:
  ask:
    source:
      kind: endpoint
      path: /held
{extra}
  shape:
    block: transform.jq
    depends_on: [ask]
    config:
      input: ${{steps.ask.output.body}}
      program: '.'
"""


def echo(extra: str = "") -> str:
    """Write the echo document, with lines added under its source."""
    return ECHO.format(extra=extra)


def held(extra: str = "", concurrency: str = "") -> str:
    """Write the held document, with lines added under its source and a concurrency policy."""
    return HELD.format(extra=extra, concurrency=concurrency)


def token_of(applied: dict[str, Any], code: str = "ask") -> str:
    """Read the token an apply minted for a source."""
    minted = [entry for entry in applied["sources"]["tokens"] if entry["code"] == code]
    assert len(minted) == 1, applied["sources"]
    return str(minted[0]["token"])


def bearer(token: str) -> dict[str, str]:
    """Present a source's token, in place of the client's own credential."""
    return {"Authorization": f"Bearer {token}"}


def inputs(client: TestClient, pipeline: str, code: str = "ask") -> list[SourceInputOut]:
    """Read a source's journal, newest first."""
    response = client.get(f"{PREFIX}/pipelines/{pipeline}/sources/{code}/inputs")
    assert response.status_code == 200, response.text
    return Page[SourceInputOut].model_validate(response.json()).items


def source(client: TestClient, pipeline: str, code: str = "ask") -> SourceOut:
    """Read one source as the API lists it."""
    response = client.get(f"{PREFIX}/pipelines/{pipeline}/sources/{code}")
    assert response.status_code == 200, response.text
    return SourceOut.model_validate(response.json())


def test_an_apply_mints_a_token_once_and_a_reapply_keeps_it(client: TestClient) -> None:
    first = apply_document(client, echo())
    token = token_of(first)
    assert first["sources"]["created"] == ["ask"]
    assert first["sources"]["tokens"][0]["url_path"] == "/endpoints/echo/{who}"
    again = apply_document(client, echo("    name: The echo"))
    assert again["sources"]["tokens"] == [], "a source keeps the token it was given"
    assert again["sources"]["updated"] == ["ask"]
    called = client.post("/endpoints/echo/ann", json={"said": "hi"}, headers=bearer(token))
    assert called.status_code == 200, called.text


def test_a_call_becomes_a_run_entered_at_the_source_with_the_request_as_its_input(client: TestClient) -> None:
    token = token_of(apply_document(client, echo()))
    called = client.post(
        "/endpoints/echo/ann?tag=a&tag=b",
        json={"said": "hi"},
        headers={**bearer(token), "X-Request-Id": "r-1"},
    )
    assert called.status_code == 200, called.text
    assert called.json() == {"said": "hi"}, "the reply is the answer"
    run_id = inputs(client, "echo")[0].run_id
    run = client.get(f"{PREFIX}/runs/{run_id}").json()["run"]
    assert run["status"] == "succeeded"
    assert run["triggered_by_kind"] == "source"
    attempts = Page[AttemptOut].model_validate(client.get(f"{PREFIX}/runs/{run_id}/attempts").json()).items
    entered = next(attempt for attempt in attempts if attempt.step_name == "ask")
    output = entered.output or {}
    assert output["path_params"] == {"who": "ann"}
    assert output["query"] == {"tag": ["a", "b"]}
    assert output["body"] == {"said": "hi"}
    assert output["headers"]["x-request-id"] == "r-1"
    assert "authorization" not in output["headers"], "the credential never reaches the input"
    answered = next(attempt for attempt in attempts if attempt.step_name == "answer")
    assert (answered.output or {})["body"] == {"said": "hi"}


@pytest.mark.parametrize("presented", [None, "Bearer not-the-token", "Basic dXNlcjpwYXNz"])
def test_a_call_without_the_sources_token_is_refused_401_and_writes_nothing(
    client: TestClient, presented: str | None
) -> None:
    apply_document(client, echo())
    headers = {"Authorization": presented} if presented else {"Authorization": ""}
    refused = client.post("/endpoints/echo/ann", json={}, headers=headers)
    assert refused.status_code == 401, refused.text
    assert refused.json()["code"] == "source.token_refused"
    assert refused.headers["www-authenticate"].startswith("Bearer")
    assert inputs(client, "echo") == []


def test_a_public_source_takes_a_call_with_no_token(client: TestClient) -> None:
    applied = apply_document(client, echo("      auth: {kind: public}"))
    assert applied["sources"]["tokens"] == [], "a public source is given no token"
    called = client.post("/endpoints/echo/ann", json={}, headers={"Authorization": ""})
    assert called.status_code == 200, called.text


def test_a_path_nothing_answers_is_404_and_a_method_its_source_does_not_answer_is_405(client: TestClient) -> None:
    token = token_of(apply_document(client, echo()))
    missing = client.post("/endpoints/nobody/here", json={}, headers=bearer(token))
    assert missing.status_code == 404, missing.text
    assert missing.json()["code"] == "source.no_route"
    assert missing.json()["params"]["path"] == "/endpoints/nobody/here"
    wrong = client.get("/endpoints/echo/ann", headers=bearer(token))
    assert wrong.status_code == 405, wrong.text
    assert wrong.headers["allow"] == "POST, PUT"


def test_the_most_literal_template_answers_first(client: TestClient) -> None:
    apply_document(client, echo("      auth: {kind: public}"))
    apply_document(
        client,
        echo("      auth: {kind: public}").replace("code: echo", "code: echo-new").replace("/echo/{who}", "/echo/new"),
    )
    called = client.post("/endpoints/echo/new", json={}, headers={"Authorization": ""})
    assert called.status_code == 200, called.text
    assert [entry.path for entry in inputs(client, "echo-new")] == ["/echo/new"]
    assert inputs(client, "echo") == []


def test_the_checks_run_in_their_order(client: TestClient) -> None:
    token = token_of(apply_document(client, echo("      max_body: 8B")))
    unauthenticated = client.post(
        "/endpoints/echo/ann", content=b"x" * 64, headers={"Authorization": "", "Content-Type": "image/png"}
    )
    assert unauthenticated.status_code == 401, "the token is checked before the content type"
    unsupported = client.post(
        "/endpoints/echo/ann", content=b"x" * 64, headers={**bearer(token), "Content-Type": "image/png"}
    )
    assert unsupported.status_code == 415, "the content type is checked before the body is read"
    oversized = client.post("/endpoints/echo/ann", json={"said": "far too much"}, headers=bearer(token))
    assert oversized.status_code == 413, oversized.text
    assert oversized.json()["params"] == {"limit": 8}
    malformed = client.post(
        "/endpoints/echo/ann", content=b"{nope", headers={**bearer(token), "Content-Type": "application/json"}
    )
    assert malformed.status_code == 400, malformed.text
    assert [entry.status for entry in inputs(client, "echo")] == [400, 413, 415]
    assert all(entry.outcome == "refused" for entry in inputs(client, "echo"))


def test_a_paused_source_is_refused_503_until_it_is_resumed(client: TestClient) -> None:
    token = token_of(apply_document(client, echo()))
    paused = client.post(f"{PREFIX}/pipelines/echo/sources/ask/$pause")
    assert paused.status_code == 200, paused.text
    assert paused.json()["state"] == "paused"
    refused = client.post("/endpoints/echo/ann", json={}, headers=bearer(token))
    assert refused.status_code == 503, refused.text
    assert refused.json()["code"] == "source.paused"
    reapplied = apply_document(client, echo("    name: The echo"))
    assert reapplied["sources"]["updated"] == ["ask"]
    assert source(client, "echo").state == "paused", "an apply keeps what an operator did"
    client.post(f"{PREFIX}/pipelines/echo/sources/ask/$resume")
    assert client.post("/endpoints/echo/ann", json={}, headers=bearer(token)).status_code == 200
    counted = source(client, "echo")
    assert (counted.accepted, counted.refused) == (1, 1)


def test_a_deactivated_pipelines_source_is_refused_503(client: TestClient) -> None:
    token = token_of(apply_document(client, echo()))
    client.post(f"{PREFIX}/pipelines/echo/$deactivate")
    refused = client.post("/endpoints/echo/ann", json={}, headers=bearer(token))
    assert refused.status_code == 503, refused.text
    assert refused.json()["code"] == "source.pipeline_inactive"
    assert source(client, "echo").state == "paused"


def test_a_rotated_token_replaces_the_old_one_at_once(client: TestClient) -> None:
    old = token_of(apply_document(client, echo()))
    rotated = client.post(f"{PREFIX}/pipelines/echo/sources/ask/$rotate-token")
    assert rotated.status_code == 200, rotated.text
    new = rotated.json()["token"]
    assert client.post("/endpoints/echo/ann", json={}, headers=bearer(old)).status_code == 401
    assert client.post("/endpoints/echo/ann", json={}, headers=bearer(new)).status_code == 200
    assert source(client, "echo").token_prefix == new[:8]


def test_a_public_source_has_no_token_to_rotate(client: TestClient) -> None:
    apply_document(client, echo("      auth: {kind: public}"))
    refused = client.post(f"{PREFIX}/pipelines/echo/sources/ask/$rotate-token")
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "source.takes_no_token"


def test_a_source_past_its_rate_is_answered_429_and_writes_no_row(client: TestClient) -> None:
    token = token_of(apply_document(client, echo("      rate: {per_minute: 1}")))
    assert client.post("/endpoints/echo/ann", json={}, headers=bearer(token)).status_code == 200
    throttled = client.post("/endpoints/echo/ann", json={}, headers=bearer(token))
    assert throttled.status_code == 429, throttled.text
    assert throttled.json()["code"] == "source.rate"
    assert throttled.headers["retry-after"] == "60"
    assert [(entry.outcome, entry.status) for entry in inputs(client, "echo")] == [("replied", 200)]


def test_a_source_with_as_many_runs_in_flight_as_it_allows_is_backlogged(client: TestClient) -> None:
    token = token_of(apply_document(client, held("      max_in_flight: 1")))
    first = client.post("/endpoints/held", json={"n": 1}, headers=bearer(token))
    assert first.status_code == 202, first.text
    listed = source(client, "held")
    assert (listed.state, listed.in_flight, listed.max_in_flight) == ("backlogged", 1, 1)
    refused = client.post("/endpoints/held", json={"n": 2}, headers=bearer(token))
    assert refused.status_code == 503, refused.text
    assert refused.json()["code"] == "source.backlogged"
    client.post(f"{PREFIX}/runs/{first.json()['run_id']}/$cancel")
    assert client.post("/endpoints/held", json={"n": 3}, headers=bearer(token)).status_code == 202


def test_a_paused_source_with_runs_in_flight_is_draining(client: TestClient) -> None:
    token = token_of(apply_document(client, held()))
    assert client.post("/endpoints/held", json={}, headers=bearer(token)).status_code == 202
    client.post(f"{PREFIX}/pipelines/held/sources/ask/$pause")
    assert source(client, "held").state == "draining"


def test_a_call_the_concurrency_policy_skips_is_refused_409(client: TestClient) -> None:
    token = token_of(apply_document(client, held(concurrency="concurrency: skip")))
    assert client.post("/endpoints/held", json={}, headers=bearer(token)).status_code == 202
    skipped = client.post("/endpoints/held", json={}, headers=bearer(token))
    assert skipped.status_code == 409, skipped.text
    assert skipped.json()["code"] == "source.run_skipped"


def test_a_route_another_pipeline_answers_is_refused_at_apply(client: TestClient) -> None:
    apply_document(client, echo())
    response = client.post(
        f"{PREFIX}/pipelines/$apply",
        json={"document": {**_loaded(echo()), "code": "echo-again"}},
    )
    assert response.status_code == 200, response.text
    plan = response.json()["plan"]
    assert plan["action"] == "invalid"
    assert [(issue["code"], issue["params"]["method"]) for issue in plan["issues"]] == [
        ("source.route_claimed", "POST"),
        ("source.route_claimed", "PUT"),
    ]
    assert {issue["location"] for issue in plan["issues"]} == {"steps.ask.source.path"}


def test_a_route_moved_between_sources_of_one_pipeline_is_not_refused_as_its_own(client: TestClient) -> None:
    apply_document(client, echo())
    moved = echo().replace("  ask:", "  asked:").replace("steps.ask.", "steps.asked.").replace("[ask]", "[asked]")
    applied = apply_document(client, moved)
    assert applied["plan"]["action"] == "update", applied
    assert applied["sources"]["created"] == ["asked"]
    assert applied["sources"]["removed"] == ["ask"]


def test_a_removed_source_stops_answering(client: TestClient) -> None:
    token = token_of(apply_document(client, echo()))
    apply_document(client, echo().replace("/echo/{who}", "/moved/{who}"))
    gone = client.post("/endpoints/echo/ann", json={}, headers=bearer(token))
    assert gone.status_code == 404, gone.text
    assert client.post("/endpoints/moved/ann", json={}, headers=bearer(token)).status_code == 200


def test_every_source_is_listed_with_its_route_and_never_its_token(client: TestClient) -> None:
    token = token_of(apply_document(client, echo()))
    apply_document(client, held())
    listed = Page[SourceOut].model_validate(client.get(f"{PREFIX}/sources").json()).items
    assert [(row.pipeline, row.code) for row in listed] == [("echo", "ask"), ("held", "ask")]
    first = listed[0]
    assert (first.kind, first.route, first.url_path, first.methods, first.auth) == (
        "endpoint",
        "/echo/{who}",
        "/endpoints/echo/{who}",
        ["POST", "PUT"],
        "token",
    )
    assert token not in client.get(f"{PREFIX}/sources").text
    one = Page[SourceOut].model_validate(client.get(f"{PREFIX}/pipelines/held/sources").json()).items
    assert [row.pipeline for row in one] == ["held"]


def test_an_unknown_source_is_404(client: TestClient) -> None:
    apply_document(client, echo())
    response = client.get(f"{PREFIX}/pipelines/echo/sources/nobody")
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "source.unknown"


def test_the_journal_pages_newest_first(client: TestClient) -> None:
    token = token_of(apply_document(client, echo()))
    for who in ("a", "b", "c"):
        client.post(f"/endpoints/echo/{who}", json={}, headers=bearer(token))
    first = client.get(f"{PREFIX}/pipelines/echo/sources/ask/inputs", params={"limit": 2}).json()
    assert [entry["path"] for entry in first["items"]] == ["/echo/c", "/echo/b"]
    rest = client.get(f"{PREFIX}/pipelines/echo/sources/ask/inputs", params={"limit": 2, "after": first["next"]}).json()
    assert [entry["path"] for entry in rest["items"]] == ["/echo/a"]
    assert rest["next"] is None


def _loaded(text: str) -> dict[str, Any]:
    """Read a document as the JSON an apply carries."""
    loaded: dict[str, Any] = yaml.safe_load(text)
    return loaded


def test_a_form_reaches_a_source_that_takes_one_and_json_does_not(client: TestClient) -> None:
    token = token_of(apply_document(client, echo("      accepts: [application/x-www-form-urlencoded]")))
    taken = client.post(
        "/endpoints/echo/ann", data={"email": "ada@example.org", "tag": ["a", "b"]}, headers=bearer(token)
    )
    assert taken.status_code == 200, taken.text
    run_id = inputs(client, "echo")[0].run_id
    attempts = Page[AttemptOut].model_validate(client.get(f"{PREFIX}/runs/{run_id}/attempts").json()).items
    entered = next(attempt for attempt in attempts if attempt.step_name == "ask").output or {}
    assert (entered["body_kind"], entered["body"]) == ("form", {"email": "ada@example.org", "tag": ["a", "b"]})
    refused = client.post("/endpoints/echo/ann", json={"email": "x"}, headers=bearer(token))
    assert refused.status_code == 415, refused.text
