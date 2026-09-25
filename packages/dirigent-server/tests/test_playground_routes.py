"""The playground's routes: the envelope, the knobs, the credential, and the setting."""

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dirigent_core.config import Settings
from dirigent_server import create_app

PREFIX = "/api/v1/playground"


@pytest.fixture
def playground(anonymous: TestClient) -> TestClient:
    """A client carrying no credential at all, which is how the playground is meant to be called."""
    return anonymous


def test_a_reflection_needs_no_credential(playground: TestClient) -> None:
    """The whole point: a step calling its own instance must not need a token."""
    body = playground.get(f"{PREFIX}/request").json()
    assert body["kind"] == "request"
    assert body["request"]["method"] == "GET"
    assert body["status"] == 200


def test_the_reflection_carries_the_query_verbatim(playground: TestClient) -> None:
    body = playground.get(f"{PREFIX}/request", params={"station": "bergen", "reading": "12.4"}).json()
    assert body["request"]["args"] == {"station": "bergen", "reading": "12.4"}
    assert body["request"]["url"].endswith("station=bergen&reading=12.4")
    assert body["request"]["path"] == f"{PREFIX}/request"


def test_a_repeated_argument_arrives_as_a_list(playground: TestClient) -> None:
    body = playground.get(f"{PREFIX}/request?tag=a&tag=b").json()
    assert body["request"]["args"]["tag"] == ["a", "b"]


def test_a_json_body_appears_once_as_json(playground: TestClient) -> None:
    """A body is decoded once and reported once, never under two names."""
    body = playground.post(f"{PREFIX}/request", json={"a": 1, "b": [2, 3]}).json()
    assert body["request"]["body"] == {"a": 1, "b": [2, 3]}
    assert body["request"]["body_kind"] == "json"
    assert body["request"]["body_bytes"] > 0
    assert body["request"]["content_type"].startswith("application/json")


def test_a_form_body_appears_once_as_form(playground: TestClient) -> None:
    body = playground.post(f"{PREFIX}/request", data={"a": "b", "c": "d"}).json()
    assert body["request"]["body"] == {"a": "b", "c": "d"}
    assert body["request"]["body_kind"] == "form"


def test_a_body_that_is_neither_is_text(playground: TestClient) -> None:
    body = playground.put(f"{PREFIX}/request", content=b"plain words", headers={"content-type": "text/plain"}).json()
    assert body["request"]["body"] == "plain words"
    assert body["request"]["body_kind"] == "text"


def test_no_body_says_so(playground: TestClient) -> None:
    body = playground.delete(f"{PREFIX}/request").json()
    assert body["request"]["body"] is None
    assert body["request"]["body_kind"] == "none"
    assert body["request"]["body_bytes"] == 0


def test_a_credential_is_reflected_as_present_and_never_as_its_value(playground: TestClient) -> None:
    """An origin that reflected a session cookie would hand it to any script on that origin."""
    response = playground.get(f"{PREFIX}/request", headers={"Authorization": "Bearer a-real-secret"})
    headers = response.json()["request"]["headers"]
    assert headers["authorization"] == "<redacted>"
    assert "a-real-secret" not in response.text


def test_a_chosen_status_is_answered_and_reflected(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/request", params={"status": 503})
    assert response.status_code == 503
    assert response.json()["status"] == 503
    assert response.json()["request"]["args"]["status"] == "503"


def test_a_status_that_carries_no_body_carries_none(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/request", params={"status": 204})
    assert response.status_code == 204
    assert response.content == b""


def test_a_delay_is_taken_before_the_answer(playground: TestClient) -> None:
    """Short enough that the test does not sleep, long enough that the knob is exercised."""
    response = playground.get(f"{PREFIX}/request", params={"delay": "50ms"})
    assert response.status_code == 200


def test_a_delay_longer_than_the_playground_allows_is_refused(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/request", params={"delay": "10m"})
    assert response.status_code == 422


def test_a_redirect_points_at_the_reflection_route(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/redirect", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == f"{PREFIX}/request"
    assert response.json()["kind"] == "redirect"
    assert response.json()["hops"] == 0


def test_a_redirect_chain_walks_itself_down(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/redirect", params={"hops": 3}, follow_redirects=False)
    assert response.json()["hops"] == 2
    assert "hops=2" in response.headers["location"]
    landed = playground.get(f"{PREFIX}/redirect", params={"hops": 3})
    assert landed.json()["kind"] == "request"


def test_a_redirect_chooses_its_status(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/redirect", params={"status": 308}, follow_redirects=False)
    assert response.status_code == 308


def test_a_status_that_is_not_a_redirect_is_refused(playground: TestClient) -> None:
    assert playground.get(f"{PREFIX}/redirect", params={"status": 200}).status_code == 422


def test_the_playground_will_not_redirect_off_this_instance(playground: TestClient) -> None:
    """An open redirect is a phishing tool wearing the instance's own domain."""
    for target in ("https://example.com", "//example.com"):
        response = playground.get(f"{PREFIX}/redirect", params={"to": target}, follow_redirects=False)
        assert response.status_code == 422, target


def test_an_unreliable_call_fails_until_the_attempt_it_names(playground: TestClient) -> None:
    failing = playground.get(f"{PREFIX}/unreliable", params={"attempt": 1, "fail_until": 2})
    assert failing.status_code == 503
    assert failing.json()["outcome"] == "failed"
    succeeding = playground.get(f"{PREFIX}/unreliable", params={"attempt": 3, "fail_until": 2})
    assert succeeding.status_code == 200
    assert succeeding.json()["outcome"] == "succeeded"
    assert succeeding.json()["attempt"] == 3


def test_an_unreliable_call_chooses_the_status_it_fails_with(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/unreliable", params={"attempt": 1, "fail_until": 1, "status": 429})
    assert response.status_code == 429


def test_response_headers_are_set_from_the_query(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/response-headers", params={"X-Station": "bergen", "X-Run": "7"})
    assert response.headers["x-station"] == "bergen"
    assert response.json()["headers"] == {"X-Station": "bergen", "X-Run": "7"}


def test_a_header_this_origin_will_not_set_is_refused(playground: TestClient) -> None:
    """Planting a cookie on this origin from a query string is not a thing to teach."""
    response = playground.get(f"{PREFIX}/response-headers", params={"Set-Cookie": "a=b"})
    assert response.status_code == 422


def test_auth_refuses_a_call_with_no_credential(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/auth")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == 'Basic realm="playground"'


def test_auth_accepts_the_documented_basic_pair(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/auth", auth=("playground", "playground"))
    assert response.status_code == 200
    assert response.json()["scheme"] == "basic"
    assert response.json()["authenticated"] is True


def test_auth_accepts_the_documented_bearer_token(playground: TestClient) -> None:
    response = playground.get(f"{PREFIX}/auth", headers={"Authorization": "Bearer playground-token"})
    assert response.json()["scheme"] == "bearer"


def test_auth_refuses_a_credential_that_is_not_the_documented_one(playground: TestClient) -> None:
    assert playground.get(f"{PREFIX}/auth", auth=("playground", "wrong")).status_code == 401
    assert playground.get(f"{PREFIX}/auth", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_every_route_answers_the_same_envelope(playground: TestClient) -> None:
    """One shape to learn: a kind, what arrived, and the route's own answer beside it."""
    for path, params in [
        ("/request", {}),
        ("/unreliable", {"attempt": 9, "fail_until": 0}),
        ("/response-headers", {}),
    ]:
        body = playground.get(f"{PREFIX}{path}", params=params).json()
        assert body["kind"], path
        assert body["request"]["method"] == "GET", path
        assert body["request"]["path"] == f"{PREFIX}{path}", path


def test_the_openapi_document_names_the_playground(client: TestClient) -> None:
    """Honest in the document rather than hidden, so a reader finds it where everything else is."""
    document = client.get("/openapi.json").json()
    paths = [path for path in document["paths"] if path.startswith(PREFIX)]
    assert f"{PREFIX}/request" in paths
    assert f"{PREFIX}/redirect" in paths
    operations = [
        operation
        for path, methods in document["paths"].items()
        if path.startswith(PREFIX)
        for operation in methods.values()
    ]
    ids = [operation["operationId"] for operation in operations]
    assert len(ids) == len(set(ids)), "an operation id is used twice"
    assert all(operation.get("summary") for operation in operations)


def test_the_setting_unmounts_the_playground() -> None:
    """Off means the routes are not there, not that they are there and refuse."""
    settings = Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        secret_key=SecretStr(Fernet.generate_key().decode()),
        playground_enabled=False,
    )
    with TestClient(create_app(settings, scheduler=False)) as client:
        assert client.get(f"{PREFIX}/request").status_code == 404
        assert f"{PREFIX}/request" not in client.get("/openapi.json").json()["paths"]
