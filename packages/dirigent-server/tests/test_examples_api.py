"""The example corpus over the API: the listing, its filters, one document, and a refusal."""

from fastapi.testclient import TestClient

PREFIX = "/api/v1"


def test_the_corpus_is_served_as_a_page(client: TestClient) -> None:
    page = client.get(f"{PREFIX}/examples", params={"limit": 500}).json()
    codes = {row["code"] for row in page["items"]}
    assert "hello-world" in codes
    row = next(one for one in page["items"] if one["code"] == "hello-world")
    assert row["plugin"] == "examples"
    assert row["starter"] is False
    assert "source" not in row


def test_a_listing_is_walked_by_its_cursor(client: TestClient) -> None:
    first = client.get(f"{PREFIX}/examples", params={"limit": 2}).json()
    assert len(first["items"]) == 2
    assert first["next"]
    second = client.get(f"{PREFIX}/examples", params={"limit": 2, "after": first["next"]}).json()
    assert {row["code"] for row in second["items"]}.isdisjoint({row["code"] for row in first["items"]})


def test_only_starters_are_served_when_the_filter_asks_for_them(client: TestClient) -> None:
    page = client.get(f"{PREFIX}/examples", params={"starter": True, "limit": 500}).json()
    assert page["items"]
    assert all(row["starter"] for row in page["items"])
    assert all("starter" in row["tags"] for row in page["items"])


def test_every_named_tag_has_to_match(client: TestClient) -> None:
    page = client.get(f"{PREFIX}/examples", params={"tag": ["starter", "http"], "limit": 500}).json()
    assert page["items"]
    assert all({"starter", "http"} <= set(row["tags"]) for row in page["items"])


def test_a_shelf_and_a_plugin_narrow_the_listing(client: TestClient) -> None:
    page = client.get(f"{PREFIX}/examples", params={"shelf": "open-data", "limit": 500}).json()
    assert page["items"]
    assert {row["shelf"] for row in page["items"]} == {"open-data"}
    assert not client.get(f"{PREFIX}/examples", params={"plugin": "nobody"}).json()["items"]


def test_one_example_is_served_with_its_source(client: TestClient) -> None:
    body = client.get(f"{PREFIX}/examples/hello-world").json()
    assert body["code"] == "hello-world"
    assert body["source"].startswith("#") or "format: dirigent/v1" in body["source"]
    assert body["path"].endswith("hello-world.yaml")
    assert set(body["requires"]) == {"blocks", "connections", "pipelines", "storage", "schemas", "workers"}


def test_an_example_nobody_ships_is_a_not_found(client: TestClient) -> None:
    response = client.get(f"{PREFIX}/examples/no-such-example")
    assert response.status_code == 404
    assert "no example 'no-such-example' is installed" in response.json()["detail"]


def test_the_corpus_is_refused_to_an_anonymous_request(anonymous: TestClient) -> None:
    assert anonymous.get(f"{PREFIX}/examples").status_code == 401
    assert anonymous.get(f"{PREFIX}/examples/hello-world").status_code == 401
