"""Text a caller writes that no database stores as written is refused where it arrives."""

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dirigent_client.enums import UserRole
from dirigent_core.auth import create_user, issue_token
from dirigent_core.config import Settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.models import Base
from dirigent_server import create_app

PREFIX: Final = "/api/v1"

#: Sent as JSON's own escapes, which is how half a surrogate pair travels at all.
JSON: Final = {"content-type": "application/json"}

#: The code every refusal of such text carries, in the request's list of problems.
UNSTORABLE: Final = "validation.text_unstorable"


def _pipeline(**extra: Any) -> dict[str, Any]:
    """A document that would apply, with whatever a case adds to it."""
    return {
        "format": "dirigent/v1",
        "code": "held-text",
        "steps": {"one": {"block": "storage.copy", "config": {"source": "a", "target": "b"}}},
        **extra,
    }


#: One call per door a caller's text comes in by, each holding text no database stores.
CALLS: Final[list[tuple[str, str, dict[str, Any]]]] = [
    (
        "post",
        "/connections",
        {"code": "a-conn", "kind": "http", "name": "held \x00 here", "config": {"base_url": "https://example.org"}},
    ),
    ("patch", "/connections/a-conn", {"description": "held \ud800 here"}),
    ("post", "/schemas", {"code": "a-schema", "description": "held \x00 here", "body": {"type": "object"}}),
    ("post", "/schemas", {"code": "a-schema", "body": {"type": "object", "title": "held \x00 here"}}),
    ("post", "/alert-rules", {"code": "a-rule", "event": "run_failed", "template": "failed \x00"}),
    ("patch", "/alert-rules/a-rule", {"body": "said \udc80"}),
    ("post", "/alert-rules/$test", {"subject": "a test \x00"}),
    ("post", "/users", {"username": "ada", "password": "a long password", "role": "viewer", "name": "A\x00da"}),
    ("post", "/users", {"username": "ada", "password": "a long password", "role": "viewer", "email": "a\x00@b.io"}),
    ("patch", "/users/tester", {"name": "held \x00 here"}),
    ("post", "/pipelines/$apply", {"document": _pipeline(description="held \x00 here")}),
    ("post", "/pipelines/$apply", {"document": _pipeline(name="held \ud800 here")}),
    ("post", "/pipelines/$apply", {"document": _pipeline(), "source_ref": "pipelines/\x00.yaml"}),
    ("post", "/pipelines/held-text/triggers/schedules", {"code": "nightly", "interval": "1h", "name": "at \x00"}),
]

IDS: Final = [
    "connection-name",
    "connection-update-surrogate",
    "schema-description",
    "schema-title",
    "alert-template",
    "alert-update-surrogate",
    "alert-test-subject",
    "user-name",
    "user-email",
    "user-update-name",
    "document-description",
    "document-name-surrogate",
    "apply-source-ref",
    "schedule-name",
]


def _answer(client: TestClient, method: str, path: str, body: dict[str, Any]) -> tuple[int, bool]:
    """Make one call, and say its status and whether it named the text it could not store."""
    answered = client.request(method, f"{PREFIX}{path}", content=json.dumps(body), headers=JSON)
    problems: list[dict[str, Any]] = answered.json().get("problems", []) if answered.status_code >= 400 else []
    return answered.status_code, UNSTORABLE in [issue["code"] for issue in problems]


def _refused(client: TestClient, method: str, path: str, body: dict[str, Any]) -> None:
    """Make one call and hold it to a 422 that names the text it could not store."""
    assert _answer(client, method, path, body) == (422, True)


@pytest.mark.parametrize(("method", "path", "body"), CALLS, ids=IDS)
def test_a_caller_writing_a_nul_or_half_a_pair_is_refused(
    client: TestClient, method: str, path: str, body: dict[str, Any]
) -> None:
    _refused(client, method, path, body)


def test_the_refusal_names_where_in_a_document_the_text_is(client: TestClient) -> None:
    document = _pipeline(steps={"one": {"block": "storage.copy", "config": {"source": "a\x00", "target": "b"}}})
    answered = client.post(f"{PREFIX}/pipelines/$apply", json={"document": document})
    assert answered.status_code == 422, answered.text
    problems = answered.json()["problems"]
    assert [(issue["code"], issue["location"]) for issue in problems] == [(UNSTORABLE, "steps.one.config.source")]


def test_text_a_database_stores_is_taken_as_written(client: TestClient) -> None:
    """A whole surrogate pair is one real character, and an escape's six characters are only text."""
    created = client.post(
        f"{PREFIX}/connections",
        json={
            "code": "a-conn",
            "kind": "http",
            "name": "\U0001f600 \\u0000",
            "config": {"base_url": "https://example.org"},
        },
    )
    assert created.status_code in (200, 201), created.text
    assert created.json()["name"] == "\U0001f600 \\u0000"


@pytest.fixture
def pg_client(postgres_url: str, tmp_path: Path) -> Iterator[TestClient]:
    """An admin client of an instance on a real PostgreSQL, its schema made afresh."""
    settings = Settings(
        database_url=postgres_url,
        artifact_root=f"file://{tmp_path / 'artifacts'}",
        secret_key=SecretStr(Fernet.generate_key().decode()),
    )

    async def prepare() -> str:
        engine = create_engine(settings)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.drop_all)
                await connection.run_sync(Base.metadata.create_all)
            async with session_scope(create_session_factory(engine)) as session:
                user = await create_user(session, "tester", "a test password", role=UserRole.ADMIN)
                issued = await issue_token(session, user, name="tests")
            return issued.secret.get_secret_value()
        finally:
            await engine.dispose()

    token = asyncio.run(prepare())
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {token}"}) as client:
        yield client


@pytest.mark.postgres
def test_postgresql_is_never_handed_what_it_would_refuse(pg_client: TestClient) -> None:
    """Every door answers 422 on PostgreSQL, which would otherwise fail the write as a 500."""
    answered = {name: _answer(pg_client, *call) for name, call in zip(IDS, CALLS, strict=True)}
    assert answered == dict.fromkeys(IDS, (422, True))
