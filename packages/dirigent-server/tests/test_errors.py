"""The one handler that renders a domain refusal as the problem document it answers with."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dirigent_core import __version__
from dirigent_core.auth import WeakPassword, WrongPassword
from dirigent_core.documents import DocumentError
from dirigent_core.pipelines import PipelineInUse, UnknownPipeline
from dirigent_core.plugins import UnknownExample
from dirigent_server.errors import INTERNAL_DETAIL, VERSION_HEADER, install_error_handlers


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
        raise DocumentError("the document does not satisfy the format", ["steps is required", "code is not a code"])

    @app.get("/refusals/example")
    async def example() -> None:
        raise UnknownExample("hello")

    @app.get("/refusals/ambiguous-example")
    async def ambiguous_example() -> None:
        raise UnknownExample("hello", ["dirigent-blocks", "dirigent-dhis2"])

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
    assert response.json()["detail"] == "steps is required; code is not a code"
    assert response.json()["problems"] == ["steps is required", "code is not a code"]


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
        "problems": [],
        "instance": "/refusals/bug",
    }
