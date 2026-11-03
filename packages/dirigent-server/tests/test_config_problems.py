"""A step's config its block's model refuses is said per field: at apply where it can be, else at run time."""

from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dirigent_core.engine.executor import Engine
from dirigent_core.engine.services import EngineServices
from dirigent_core.messages import CONFIG_INVALID
from tests_support import apply_document

PREFIX = "/api/v1"

DELAYED = """
format: dirigent/v1
kind: pipeline
code: delayed
params:
  type: object
  properties:
    pause: {type: string}
steps:
  wait:
    block: playground.generate
    config:
      delay: ${params.pause}
"""

LITERAL = """
format: dirigent/v1
kind: pipeline
code: literal
steps:
  wait:
    block: playground.generate
    config:
      delay: 60s
"""


def drain(client: TestClient) -> None:
    """Claim and run everything due, as a worker would."""
    app = cast("FastAPI", client.app)
    engine = Engine(app.state.session_factory, cast("EngineServices", app.state.services), owner="test-worker")

    async def everything() -> None:
        for _ in range(20):
            unit = await engine.claim()
            if unit is None:
                return
            await engine.run_unit(unit)

    assert client.portal is not None
    client.portal.call(everything)


def test_a_config_its_block_refuses_at_run_time_fails_with_each_problem_coded_and_located(client: TestClient) -> None:
    apply_document(client, DELAYED)
    started = client.post(f"{PREFIX}/pipelines/delayed/$run", json={"params": {"pause": "60s"}})
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]

    drain(client)

    attempt = client.get(f"{PREFIX}/runs/{run_id}/attempts").json()["items"][0]
    assert attempt["status"] == "failed"
    assert attempt["error_code"] == CONFIG_INVALID.code
    problems: list[dict[str, Any]] = attempt["error_params"]["problems"]
    assert [(one["code"], one["location"], one["params"]["limit"]) for one in problems] == [
        ("validation.less_than_equal", "delay", "30s")
    ]
    assert attempt["error_params"]["field"] == "delay"
    assert attempt["error_params"]["more"] == ""

    listed = client.get(f"{PREFIX}/runs", params={"pipeline": "delayed"}).json()["items"][0]
    assert listed["error_code"] == CONFIG_INVALID.code
    assert listed["failed_step"] == "wait"
    assert listed["error_params"]["problems"] == problems


def test_a_literal_config_its_block_refuses_is_refused_at_apply_at_the_field(client: TestClient) -> None:
    plan = apply_document(client, LITERAL)["plan"]
    assert plan["action"] == "invalid"
    problems = plan["issues"]
    assert [(one["code"], one["location"], one["params"]["limit"]) for one in problems] == [
        ("validation.less_than_equal", "steps.wait.config.delay", "30s")
    ]
