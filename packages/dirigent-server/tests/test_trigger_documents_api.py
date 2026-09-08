"""``/trigger-documents``: reading and removing the clock files applied over a pipeline."""

from typing import Any

import yaml
from fastapi.testclient import TestClient

from tests_support import apply_document

PREFIX = "/api/v1"

PIPELINE = """
format: dirigent/v1
kind: pipeline
code: batch-fleet
description: A pipeline somebody else's document schedules.
steps:
  greet:
    block: shell.run
    config:
      argv: [echo, hello]
triggers:
  schedules:
    - code: inline-nightly
      cron: "0 5 * * *"
"""

TRIGGERS = """
format: dirigent/v1
kind: triggers
code: fleet-clocks
name: Fleet clocks
description: The operations team's clocks.
pipeline: batch-fleet
triggers:
  schedules:
    - code: ops-nightly
      cron: "0 4 * * *"
  webhooks:
    - code: ops-kick
      params_from_payload: { day: "$.run.date" }
"""


def stand_up(client: TestClient) -> dict[str, Any]:
    """Apply the pipeline, then the triggers document that schedules it."""
    apply_document(client, PIPELINE)
    return apply_document(client, TRIGGERS)


def test_applying_a_triggers_document_reports_the_kind_and_its_target(client: TestClient) -> None:
    result = stand_up(client)

    assert result["kind"] == "triggers"
    assert result["version"] is None
    assert result["plan"]["action"] == "create"
    assert result["plan"]["pipeline"] == "batch-fleet"
    assert result["triggers"]["schedules_created"] == ["ops-nightly"]


def test_a_document_naming_a_pipeline_no_instance_holds_is_invalid(client: TestClient) -> None:
    result = apply_document(client, TRIGGERS)

    assert result["plan"]["action"] == "invalid"
    assert result["plan"]["issues"][0]["location"] == "pipeline"


def test_the_listing_names_the_pipeline_each_one_fires(client: TestClient) -> None:
    stand_up(client)

    listed = client.get(f"{PREFIX}/trigger-documents")

    assert listed.status_code == 200, listed.text
    rows = listed.json()["items"]
    assert [(row["code"], row["pipeline"]) for row in rows] == [("fleet-clocks", "batch-fleet")]
    assert rows[0]["name"] == "Fleet clocks"


def test_reading_one_carries_the_document_and_the_rows_it_owns(client: TestClient) -> None:
    stand_up(client)

    detail = client.get(f"{PREFIX}/trigger-documents/fleet-clocks")

    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["schedules"] == ["ops-nightly"]
    assert body["webhooks"] == ["ops-kick"]
    assert body["document"]["kind"] == "triggers"
    assert body["digest"].startswith("sha256:")


def test_an_unknown_code_is_a_404(client: TestClient) -> None:
    assert client.get(f"{PREFIX}/trigger-documents/nothing").status_code == 404


def test_a_schedule_says_which_document_declares_it(client: TestClient) -> None:
    stand_up(client)

    rows = client.get(f"{PREFIX}/pipelines/batch-fleet/triggers/schedules").json()["items"]

    owners = {row["code"]: row["trigger_document"] for row in rows}
    assert owners == {"inline-nightly": None, "ops-nightly": "fleet-clocks"}


def test_a_webhook_says_which_document_declares_it(client: TestClient) -> None:
    stand_up(client)

    row = client.get(f"{PREFIX}/pipelines/batch-fleet/triggers/webhooks/ops-kick").json()

    assert row["trigger_document"] == "fleet-clocks"
    assert row["managed"] is True


def test_deleting_one_removes_its_rows_and_leaves_the_pipelines_own(client: TestClient) -> None:
    stand_up(client)

    removed = client.delete(f"{PREFIX}/trigger-documents/fleet-clocks")

    assert removed.status_code == 204, removed.text
    rows = client.get(f"{PREFIX}/pipelines/batch-fleet/triggers/schedules").json()["items"]
    assert [row["code"] for row in rows] == ["inline-nightly"]
    assert client.get(f"{PREFIX}/pipelines/batch-fleet/triggers/webhooks").json()["items"] == []


def test_deleting_an_unknown_one_is_a_404(client: TestClient) -> None:
    assert client.delete(f"{PREFIX}/trigger-documents/nothing").status_code == 404


def test_an_operator_may_remove_one(operator: TestClient, client: TestClient) -> None:
    stand_up(client)

    assert operator.delete(f"{PREFIX}/trigger-documents/fleet-clocks").status_code == 204


def test_a_viewer_may_read_but_not_remove(viewer: TestClient, client: TestClient) -> None:
    stand_up(client)

    assert viewer.get(f"{PREFIX}/trigger-documents").status_code == 200
    assert viewer.delete(f"{PREFIX}/trigger-documents/fleet-clocks").status_code == 403


def test_a_prune_deletes_a_directory_documents_clocks(client: TestClient) -> None:
    apply_document(client, PIPELINE)
    applied = client.post(
        f"{PREFIX}/pipelines/$apply",
        json={"document": _as_json(TRIGGERS), "source": "directory", "source_ref": "clocks.yaml"},
    )
    assert applied.status_code == 200, applied.text

    pruned = client.post(f"{PREFIX}/pipelines/$prune", json={"keep": ["batch-fleet"]})

    assert pruned.status_code == 200, pruned.text
    assert pruned.json()["trigger_documents_removed"] == ["fleet-clocks"]
    rows = client.get(f"{PREFIX}/pipelines/batch-fleet/triggers/schedules").json()["items"]
    assert [row["code"] for row in rows] == ["inline-nightly"]


def _as_json(text: str) -> dict[str, Any]:
    """Read a document's YAML as the JSON body the apply route takes."""
    return dict(yaml.safe_load(text))
