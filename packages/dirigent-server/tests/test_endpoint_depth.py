"""A body nested too deep is refused at the door, and a stored value that deep cannot wedge the claim."""

from typing import Any, cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dirigent_core.engine.executor import Engine
from dirigent_core.engine.services import EngineServices
from dirigent_core.messages import CONFIG_FAILED, CONFIG_REFUSED, ENDPOINT_BODY_TOO_DEEP
from dirigent_core.models import StepAttempt
from dirigent_core.sources.endpoint import MAX_BODY_DEPTH
from tests_support import apply_document

PREFIX = "/api/v1"

#: How far down pydantic walks a value, and past it a validation raises.
PYDANTIC_WALKS = 255


def poisoned(config: str, *, extra: str = "") -> str:
    """Write a public source and a step depending on it, holding the config given."""
    return f"""
format: dirigent/v1
kind: pipeline
code: poison
steps:
  ask:
    source:
      kind: endpoint
      path: /poison
      auth: {{kind: public}}
  shape:
    block: transform.jq
    depends_on: [ask]
{extra}
    config: {config}
"""


OTHER = """
format: dirigent/v1
kind: pipeline
code: other
steps:
  one:
    block: transform.jq
    config: {input: 1, program: '.'}
  two:
    block: transform.jq
    depends_on: [one]
    config: {input: 2, program: '.'}
"""


def nested_text(depth: int) -> str:
    """Write a JSON list holding itself ``depth`` levels down."""
    return "[" * depth + "]" * depth


def nested_value(depth: int) -> list[Any]:
    """Build what :func:`nested_text` writes."""
    value: list[Any] = []
    for _ in range(depth - 1):
        value = [value]
    return value


def post(client: TestClient, text: str) -> Any:
    """Call the source with no credential and a raw JSON body."""
    return client.post(
        "/endpoints/poison", content=text, headers={"Authorization": "", "Content-Type": "application/json"}
    )


def start(client: TestClient, pipeline: str) -> str:
    """Start a run by hand and return its id."""
    started = client.post(f"{PREFIX}/pipelines/{pipeline}/$run", json={"params": {}})
    assert started.status_code == 202, started.text
    return str(started.json()["run_id"])


def store_at_source(client: TestClient, run_id: str, depth: int) -> None:
    """Write a body of this depth over what the source's attempt stored, the way another kind could have."""
    app = cast("FastAPI", client.app)

    async def write() -> None:
        async with app.state.session_factory() as session:
            await session.execute(
                sa.update(StepAttempt)
                .where(StepAttempt.run_id == UUID(run_id), StepAttempt.step_name == "ask")
                .values(output={"body": nested_value(depth)})
            )
            await session.commit()

    assert client.portal is not None
    client.portal.call(write)


def drain(client: TestClient) -> int:
    """Claim and run everything due, as a worker would, and count how many units ran."""
    app = cast("FastAPI", client.app)
    engine = Engine(app.state.session_factory, cast("EngineServices", app.state.services), owner="test-worker")

    async def everything() -> int:
        for ran in range(50):
            unit = await engine.claim()
            if unit is None:
                return ran
            await engine.run_unit(unit)
        raise AssertionError("the claim never ran out of work")

    assert client.portal is not None
    return client.portal.call(everything)


def attempts_of(client: TestClient, run_id: str) -> dict[str, dict[str, Any]]:
    """Read a run's attempts, keyed by step, through the rows a claim wrote."""
    app = cast("FastAPI", client.app)

    async def read() -> dict[str, dict[str, Any]]:
        async with app.state.session_factory() as session:
            rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == UUID(run_id)))
            return {row.step_name: {"status": row.status.value, "error_code": row.error_code} for row in rows.scalars()}

    assert client.portal is not None
    return client.portal.call(read)


@pytest.mark.parametrize("depth", [MAX_BODY_DEPTH + 1, PYDANTIC_WALKS - 1, PYDANTIC_WALKS, 200_000])
def test_a_body_past_the_limit_is_refused_and_starts_no_run(client: TestClient, depth: int) -> None:
    apply_document(client, poisoned("{input: 1, program: '.'}"))
    answered = post(client, nested_text(depth))
    assert answered.status_code == 400, answered.text
    assert answered.json()["code"] == ENDPOINT_BODY_TOO_DEEP.code
    assert answered.json()["params"]["limit"] == MAX_BODY_DEPTH
    assert drain(client) == 0


def test_a_body_at_the_limit_runs_and_reads_back(client: TestClient) -> None:
    apply_document(client, poisoned("{input: '${steps.ask.output.body}', program: '.'}"))
    answered = post(client, nested_text(MAX_BODY_DEPTH))
    assert answered.status_code == 202, answered.text
    assert drain(client) == 1
    run_id = answered.json()["run_id"]
    assert client.get(f"{PREFIX}/runs/{run_id}").json()["run"]["status"] == "succeeded"
    assert client.get(f"{PREFIX}/runs/{run_id}/attempts").status_code == 200


@pytest.mark.parametrize(
    ("config", "status", "code"),
    [
        ("{input: 1, program: '.'}", "succeeded", None),
        ("{input: {a: {b: '${steps.ask.output.body}'}}, program: '.'}", "failed", CONFIG_REFUSED.code),
    ],
    ids=["a-step-not-reading-it", "a-step-reading-it"],
)
def test_a_stored_output_past_what_pydantic_walks_leaves_the_step_settled_and_other_work_claimable(
    client: TestClient, config: str, status: str, code: str | None
) -> None:
    apply_document(client, poisoned(config))
    apply_document(client, OTHER)
    accepted = post(client, "{}")
    assert accepted.status_code == 202, accepted.text
    poison = accepted.json()["run_id"]
    store_at_source(client, poison, PYDANTIC_WALKS + 10)
    other_id = start(client, "other")

    assert drain(client) >= 2

    settled = attempts_of(client, poison)
    assert settled["shape"] == {"status": status, "error_code": code}
    assert {row["status"] for row in attempts_of(client, other_id).values()} == {"succeeded"}


def test_a_step_deadline_past_what_a_date_holds_fails_the_step_and_other_work_runs(client: TestClient) -> None:
    apply_document(client, poisoned("{input: 1, program: '.'}", extra="    deadline: 3000000d"))
    apply_document(client, OTHER)
    accepted = post(client, "{}")
    assert accepted.status_code == 202, accepted.text
    other_id = start(client, "other")

    drain(client)

    settled = attempts_of(client, accepted.json()["run_id"])
    assert settled["shape"] == {"status": "failed", "error_code": CONFIG_FAILED.code}
    assert {row["status"] for row in attempts_of(client, other_id).values()} == {"succeeded"}
