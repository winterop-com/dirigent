"""A value nested past what a run stores fails where it would be stored, and an older one never takes a read down."""

from typing import Any, cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dirigent_common.depth import MAX_STORED_DEPTH, nests_past
from dirigent_common.messages import VALUE_NOT_SHOWN
from dirigent_core.engine.executor import Engine
from dirigent_core.engine.services import EngineServices
from dirigent_core.messages import INPUT_TOO_DEEP, OUTPUT_TOO_DEEP, PARAMETERS_TOO_DEEP
from dirigent_core.models import Notification, Run, StepAttempt
from tests_support import apply_document

PREFIX = "/api/v1"

#: Deep enough that a page or a report holding it is past what pydantic serialises.
PAST_PYDANTIC = 253


def nested_value(depth: int) -> list[Any]:
    """A JSON list holding itself ``depth`` levels down."""
    value: list[Any] = []
    for _ in range(depth - 1):
        value = [value]
    return value


def deepening(depth: int) -> str:
    """A pipeline whose one step answers with a list nested ``depth`` levels, then one after it."""
    return f"""
format: dirigent/v1
kind: pipeline
code: deepening
params:
  type: object
  properties:
    x: {{}}
steps:
  make:
    block: transform.jq
    config: {{input: 1, program: 'reduce range({depth - 1}) as $i ([]; [.])'}}
  after:
    block: transform.jq
    depends_on: [make]
    config: {{input: 1, program: '.'}}
"""


ENTERED = """
format: dirigent/v1
kind: pipeline
code: entered
steps:
  ask:
    source:
      kind: endpoint
      path: /entered
      auth: {kind: public}
  after:
    block: transform.jq
    depends_on: [ask]
    config: {input: 1, program: '.'}
"""


def drain(client: TestClient) -> None:
    """Claim and run everything due, as a worker would."""
    app = cast("FastAPI", client.app)
    engine = Engine(app.state.session_factory, cast("EngineServices", app.state.services), owner="test-worker")

    async def everything() -> None:
        for _ in range(50):
            unit = await engine.claim()
            if unit is None:
                return
            await engine.run_unit(unit)
        raise AssertionError("the claim never ran out of work")

    assert client.portal is not None
    client.portal.call(everything)


def attempts_of(client: TestClient, run_id: str) -> dict[str, dict[str, Any]]:
    """Read a run's attempts, keyed by step, through the rows the engine wrote."""
    app = cast("FastAPI", client.app)

    async def read() -> dict[str, dict[str, Any]]:
        async with app.state.session_factory() as session:
            rows = await session.execute(sa.select(StepAttempt).where(StepAttempt.run_id == UUID(run_id)))
            return {
                row.step_name: {"status": row.status.value, "error_code": row.error_code, "params": row.error_params}
                for row in rows.scalars()
            }

    assert client.portal is not None
    return client.portal.call(read)


def write_directly(client: TestClient, run_id: str, depth: int, *, outputs: bool) -> None:
    """Store a value of this depth as a run's parameters, or its attempts' outputs, as an older release could."""
    app = cast("FastAPI", client.app)

    async def write() -> None:
        async with app.state.session_factory() as session:
            if outputs:
                await session.execute(
                    sa.update(StepAttempt)
                    .where(StepAttempt.run_id == UUID(run_id))
                    .values(output={"value": nested_value(depth)})
                )
            else:
                await session.execute(
                    sa.update(Run).where(Run.id == UUID(run_id)).values(params={"x": nested_value(depth)})
                )
            await session.commit()

    assert client.portal is not None
    client.portal.call(write)


def notifications_for(client: TestClient, run_id: str) -> int:
    """Count the alerts queued for a run."""
    app = cast("FastAPI", client.app)

    async def count() -> int:
        async with app.state.session_factory() as session:
            found = await session.execute(
                sa.select(sa.func.count()).select_from(Notification).where(Notification.run_id == UUID(run_id))
            )
            return int(found.scalar_one())

    assert client.portal is not None
    return client.portal.call(count)


def start(client: TestClient, pipeline: str, **body: Any) -> str:
    """Start a run by hand and return its id."""
    started = client.post(f"{PREFIX}/pipelines/{pipeline}/$run", json={"params": {}, **body})
    assert started.status_code == 202, started.text
    return str(started.json()["run_id"])


@pytest.mark.parametrize("depth", [MAX_STORED_DEPTH, PAST_PYDANTIC])
def test_a_step_output_past_the_bound_fails_the_step_and_every_read_answers(client: TestClient, depth: int) -> None:
    apply_document(client, deepening(depth))
    run_id = start(client, "deepening")
    drain(client)

    settled = attempts_of(client, run_id)
    assert settled["make"]["status"] == "failed"
    assert settled["make"]["error_code"] == OUTPUT_TOO_DEEP.code
    assert settled["make"]["params"] == {"limit": MAX_STORED_DEPTH}
    assert client.get(f"{PREFIX}/runs/{run_id}/attempts").status_code == 200
    assert client.get(f"{PREFIX}/runs").status_code == 200


def test_a_step_output_inside_the_bound_is_stored(client: TestClient) -> None:
    apply_document(client, deepening(MAX_STORED_DEPTH - 2))
    run_id = start(client, "deepening")
    drain(client)

    assert {row["status"] for row in attempts_of(client, run_id).values()} == {"succeeded"}


def test_parameters_past_the_bound_refuse_the_run(client: TestClient) -> None:
    apply_document(client, deepening(2))
    refused = client.post(f"{PREFIX}/pipelines/deepening/$run", json={"params": {"x": nested_value(PAST_PYDANTIC)}})
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == PARAMETERS_TOO_DEEP.code
    assert client.get(f"{PREFIX}/runs").status_code == 200


def test_an_input_past_the_bound_fails_its_source_and_the_run_reads_back(client: TestClient) -> None:
    apply_document(client, ENTERED)
    run_id = start(client, "entered", input={"body": nested_value(PAST_PYDANTIC)})
    drain(client)

    settled = attempts_of(client, run_id)
    assert settled["ask"]["status"] == "failed"
    assert settled["ask"]["error_code"] == INPUT_TOO_DEEP.code
    assert settled["after"]["status"] != "succeeded"
    assert client.get(f"{PREFIX}/runs/{run_id}").json()["run"]["status"] == "failed"
    assert client.get(f"{PREFIX}/runs/{run_id}/attempts").status_code == 200
    assert client.get(f"{PREFIX}/runs").status_code == 200


def test_a_row_stored_past_the_bound_is_shown_cut_and_never_takes_a_list_down(client: TestClient) -> None:
    client.post(f"{PREFIX}/alert-rules", json={"code": "watch", "event": "run_succeeded"})
    apply_document(client, deepening(2))
    bystander = start(client, "deepening")
    run_id = start(client, "deepening")
    write_directly(client, run_id, PAST_PYDANTIC + 1, outputs=False)
    drain(client)
    write_directly(client, run_id, PAST_PYDANTIC + 1, outputs=True)

    attempts = client.get(f"{PREFIX}/runs/{run_id}/attempts")
    assert attempts.status_code == 200, attempts.text
    marker = VALUE_NOT_SHOWN.render(limit=MAX_STORED_DEPTH)
    outputs = [row["output"] for row in attempts.json()["items"]]
    assert len(outputs) == 2
    for output in outputs:
        assert marker in repr(output)
        assert not nests_past(output)
    listed = client.get(f"{PREFIX}/runs")
    assert listed.status_code == 200, listed.text
    mine = next(row for row in listed.json()["items"] if row["id"] == run_id)
    assert marker in repr(mine["params"])
    assert not nests_past(mine["params"])
    assert {row["id"] for row in listed.json()["items"]} >= {run_id, bystander}
    assert notifications_for(client, run_id) == 1
    assert notifications_for(client, bystander) == 1
