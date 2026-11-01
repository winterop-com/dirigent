"""A pipeline with a source is run by hand over the API, with an input or its source's sample."""

from typing import Any

from fastapi.testclient import TestClient

from dirigent_client.schemas import AttemptOut, Page
from tests_support import apply_document

PREFIX = "/api/v1"

ECHO = """
format: dirigent/v1
kind: pipeline
code: echo-by-hand
steps:
  ask:
    source:
      kind: endpoint
      path: /echo
      methods: [POST]
    sample:
      body: {said: from the sample}
  answer:
    depends_on: [ask]
    reply:
      status: 200
      body: ${steps.ask.output.body}
"""


def run(client: TestClient, body: dict[str, Any]) -> tuple[str, Any]:
    """Start a run of the echo pipeline, and read its status and what its reply rendered."""
    accepted = client.post(f"{PREFIX}/pipelines/echo-by-hand/$run", json=body)
    assert accepted.status_code == 202, accepted.text
    run_id = accepted.json()["run_id"]
    detail = client.get(f"{PREFIX}/runs/{run_id}")
    assert detail.status_code == 200, detail.text
    page = Page[AttemptOut].model_validate(client.get(f"{PREFIX}/runs/{run_id}/attempts").json())
    reply = next(attempt for attempt in page.items if attempt.step_name == "answer")
    return detail.json()["run"]["status"], (reply.output or {}).get("body")


def test_a_hand_run_with_no_input_takes_the_sources_sample(client: TestClient) -> None:
    apply_document(client, ECHO)
    status, body = run(client, {"params": {}})
    assert status == "succeeded", "a source and a reply are both the server's to settle"
    assert body == {"said": "from the sample"}


def test_a_hand_run_given_an_input_answers_with_it(client: TestClient) -> None:
    apply_document(client, ECHO)
    _, body = run(client, {"params": {}, "source": "ask", "input": {"body": {"said": "by hand"}}})
    assert body == {"said": "by hand"}


def entered(client: TestClient, body: dict[str, Any]) -> tuple[str | None, Any]:
    """Start a run of the echo pipeline, and read how its source was entered and whether its reply was sent."""
    accepted = client.post(f"{PREFIX}/pipelines/echo-by-hand/$run", json=body)
    assert accepted.status_code == 202, accepted.text
    run_id = accepted.json()["run_id"]
    page = Page[AttemptOut].model_validate(client.get(f"{PREFIX}/runs/{run_id}/attempts").json())
    by_step = {attempt.step_name: attempt for attempt in page.items}
    assert by_step["answer"].via is None, "only a source's attempt says how its input arrived"
    return by_step["ask"].via, (by_step["answer"].output or {}).get("delivered")


def test_a_hand_run_with_no_input_says_it_entered_with_the_sample_and_sent_nothing(client: TestClient) -> None:
    apply_document(client, ECHO)
    assert entered(client, {"params": {}}) == ("sample", False)


def test_a_hand_run_given_an_input_says_it_was_given_by_hand(client: TestClient) -> None:
    apply_document(client, ECHO)
    assert entered(client, {"params": {}, "input": {"body": {"said": "by hand"}}}) == ("hand", False)


def test_an_input_the_source_cannot_take_is_refused_before_a_run_exists(client: TestClient) -> None:
    apply_document(client, ECHO)
    refused = client.post(f"{PREFIX}/pipelines/echo-by-hand/$run", json={"params": {}, "input": {"method": "GET"}})
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "run.entry_input_refused"


def test_naming_a_step_that_is_not_a_source_is_refused(client: TestClient) -> None:
    apply_document(client, ECHO)
    refused = client.post(f"{PREFIX}/pipelines/echo-by-hand/$run", json={"params": {}, "source": "answer"})
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "run.entry_not_a_source"
