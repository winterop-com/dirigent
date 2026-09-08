"""Helpers the API tests share: one document, and a function that applies it."""

from typing import Any

import yaml
from fastapi.testclient import TestClient

USERNAME = "tester"
PASSWORD = "a test password"

DOCUMENT = """
format: dirigent/v1
kind: pipeline
code: api-demo
description: Two shell steps, so the API has something real to talk about.
params:
  type: object
  properties:
    greeting:
      type: string
      default: hello from the api
steps:
  greet:
    block: shell.run
    config:
      argv: [echo, "${params.greeting}"]
  farewell:
    block: shell.run
    depends_on: [greet]
    config:
      argv: [echo, goodbye]
"""


def apply_document(
    client: TestClient, text: str, *, dry_run: bool = False, pause_schedules: bool = False
) -> dict[str, Any]:
    """Apply a YAML document through the API and return the parsed result."""
    response = client.post(
        "/api/v1/pipelines/$apply",
        json={"document": yaml.safe_load(text), "pause_schedules": pause_schedules},
        params={"dry_run": dry_run} if dry_run else None,
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body
