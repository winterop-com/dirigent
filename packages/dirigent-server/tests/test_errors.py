"""The one handler that renders a domain refusal as the problem document it answers with."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dirigent_common import Issue
from dirigent_core import __version__
from dirigent_core.auth import WeakPassword, WrongPassword
from dirigent_core.documents import DocumentError
from dirigent_core.messages import DOCUMENT_UNSATISFIED, STEP_CONFIG_INVALID
from dirigent_core.pipelines import PipelineInUse, UnknownPipeline
from dirigent_core.plugins import UnknownExample
from dirigent_server.errors import INTERNAL_DETAIL, VERSION_HEADER, install_error_handlers
from dirigent_server.messages import HTTP_ERROR, INTERNAL, REQUEST_INVALID


@pytest.fixture
def refusals() -> TestClient:
    """An application whose every route raises, so only the handlers answer."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/refusals/missing")
    async def missing() -> None:
        raise UnknownPipeline("nightly")

    @app.get("/refusals/in-use")
    async def in_use() -> None:
        raise PipelineInUse("nightly", 2)

    @app.get("/refusals/weak")
    async def weak() -> None:
        raise WeakPassword()

    @app.get("/refusals/wrong")
    async def wrong() -> None:
        raise WrongPassword()

    @app.get("/refusals/document")
    async def document() -> None:
        raise DocumentError(
            DOCUMENT_UNSATISFIED,
            problems=[
                Issue.of(STEP_CONFIG_INVALID, detail="steps is required"),
                Issue.of(STEP_CONFIG_INVALID, detail="code is not a code"),
            ],
            format="dirigent/v1",
        )

    @app.get("/refusals/example")
    async def example() -> None:
        raise UnknownExample("hello")

    @app.get("/refusals/ambiguous-example")
    async def ambiguous_example() -> None:
        raise UnknownExample("hello", ["dirigent-blocks", "dirigent-dhis2"])

    @app.get("/refusals/validated")
    async def validated(code: int) -> None:  # pyright: ignore[reportUnusedParameter]
        return None  # pragma: no cover - the query is refused before the body runs

    @app.get("/refusals/bug")
    async def bug() -> None:
        raise RuntimeError("a connection string nobody should be shown")

    return TestClient(app, raise_server_exceptions=False)


def test_a_refusal_renders_at_the_status_its_class_carries(refusals: TestClient) -> None:
    response = refusals.get("/refusals/missing")

    assert response.status_code == 404
    assert response.headers[VERSION_HEADER] == __version__
    assert response.json() == {
        "status": 404,
        "title": "Not Found",
        "detail": "no pipeline coded 'nightly'",
        "code": "pipeline.unknown",
        "params": {"code": "'nightly'"},
        "problems": [],
        "instance": "/refusals/missing",
    }


def test_a_conflict_and_a_forbidden_carry_their_own_statuses(refusals: TestClient) -> None:
    conflict = refusals.get("/refusals/in-use")
    forbidden = refusals.get("/refusals/wrong")

    assert conflict.status_code == 409
    assert conflict.json()["title"] == "Conflict"
    assert "still in flight" in conflict.json()["detail"]
    assert forbidden.status_code == 403
    assert forbidden.json()["title"] == "Forbidden"
    assert forbidden.json()["detail"] == "the current password is not correct"


def test_a_refusal_with_no_status_of_its_own_is_unprocessable(refusals: TestClient) -> None:
    response = refusals.get("/refusals/weak")

    assert response.status_code == 422
    assert response.json()["title"] == "Unprocessable Content"
    assert response.json()["problems"] == []


def test_a_refusal_that_carries_a_list_answers_with_every_problem(refusals: TestClient) -> None:
    response = refusals.get("/refusals/document")

    assert response.status_code == 422
    assert response.json()["code"] == "document.unsatisfied"
    assert response.json()["detail"] == "steps is required; code is not a code"
    assert [one["message"] for one in response.json()["problems"]] == [
        "steps is required",
        "code is not a code",
    ]
    assert {one["code"] for one in response.json()["problems"]} == {"document.step_config_invalid"}


def test_an_example_is_a_conflict_when_two_plugins_claim_it_and_a_404_when_none_does(
    refusals: TestClient,
) -> None:
    unknown = refusals.get("/refusals/example")
    ambiguous = refusals.get("/refusals/ambiguous-example")

    assert unknown.status_code == 404
    assert "no example 'hello' is installed" in unknown.json()["detail"]
    assert ambiguous.status_code == 409
    assert "does not name one of them" in ambiguous.json()["detail"]


def test_an_exception_that_is_not_a_refusal_still_says_nothing(refusals: TestClient) -> None:
    response = refusals.get("/refusals/bug")

    assert response.status_code == 500
    assert response.headers[VERSION_HEADER] == __version__
    assert response.json() == {
        "status": 500,
        "title": "Internal Server Error",
        "detail": INTERNAL_DETAIL,
        "code": INTERNAL.code,
        "params": {},
        "problems": [],
        "instance": "/refusals/bug",
    }


def test_a_request_the_framework_refuses_is_coded_as_the_servers_own(refusals: TestClient) -> None:
    missing = refusals.get("/refusals/nothing-here")
    invalid = refusals.get("/refusals/validated")

    assert missing.json()["code"] == HTTP_ERROR.code
    assert missing.json()["params"]["status"] == 404
    assert invalid.status_code == 422
    assert invalid.json()["code"] == REQUEST_INVALID.code
    assert invalid.json()["problems"][0]["code"] == "validation.missing"


def test_every_handler_answers_with_the_code_of_the_message_it_rendered(refusals: TestClient) -> None:
    assert refusals.get("/refusals/weak").json()["code"] == "auth.weak_password"
    assert refusals.get("/refusals/wrong").json()["code"] == "auth.wrong_password"
    assert refusals.get("/refusals/in-use").json()["code"] == "pipeline.in_use"
    assert refusals.get("/refusals/example").json()["code"] == "host.unknown_example"
    assert refusals.get("/refusals/ambiguous-example").json()["code"] == "host.ambiguous_example"
