"""The bundled web UI: what the server serves for it, and what it leaves alone.

Every test builds its own application, because whether a bundle exists is decided while the
application is built rather than per request.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dirigent_core import __version__
from dirigent_core.config import Settings
from dirigent_server import create_app, ui

SHELL = "<!doctype html><title>dirigent</title><script src=/assets/app-abc123.js></script>"
ASSET = "assets/app-abc123.js"
IMMUTABLE = "public, max-age=31536000, immutable"
CLIENT_ROUTE = "/runs/6f1f6b0e-4c1e-4d0a-9d9c-2f2f9b7f7a11"

#: What a browser navigating to a page sends, and what `fetch` does not.
NAVIGATING = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


@pytest.fixture
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A built bundle where an installed wheel carries one."""
    directory = tmp_path / "static"
    (directory / "assets").mkdir(parents=True)
    (directory / "index.html").write_text(SHELL)
    (directory / ASSET).write_text("console.log('dirigent')")
    (directory / "favicon.ico").write_bytes(b"\x00\x00\x01\x00")
    monkeypatch.setattr(ui, "PACKAGED_STATIC", directory)
    monkeypatch.setattr(ui, "CHECKOUT_STATIC", tmp_path / "never")
    return directory


@pytest.fixture
def no_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An instance whose UI is enabled and never built, whatever the checkout holds."""
    monkeypatch.setattr(ui, "PACKAGED_STATIC", tmp_path / "never-installed")
    monkeypatch.setattr(ui, "CHECKOUT_STATIC", tmp_path / "never-built")


@pytest.fixture
def served(settings: Settings, admin_token: str, bundle: Path) -> Iterator[TestClient]:
    """A client of an instance that has a bundle, authenticated as an admin."""
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        yield client


@pytest.fixture
def unbuilt(settings: Settings, admin_token: str, no_bundle: None) -> Iterator[TestClient]:
    """A client of an instance whose UI is enabled and unbuilt."""
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        yield client


@pytest.fixture
def api_only(settings: Settings, admin_token: str, bundle: Path) -> Iterator[TestClient]:
    """A client of an instance that has a bundle and is configured to serve none of it."""
    off = settings.model_copy(update={"ui_enabled": False})
    with TestClient(create_app(off), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        yield client


def test_the_shell_is_served_at_the_root_and_never_cached(served: TestClient) -> None:
    response = served.get("/")
    assert response.status_code == 200
    assert response.text == SHELL
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


def test_a_hashed_asset_is_served_immutable(served: TestClient) -> None:
    response = served.get(f"/{ASSET}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == IMMUTABLE


def test_a_missing_asset_is_a_refusal_rather_than_the_shell(served: TestClient) -> None:
    response = served.get("/assets/app-deleted.js")
    assert response.status_code == 404
    assert response.json()["status"] == 404


def test_a_navigation_to_a_client_route_is_answered_with_the_shell(served: TestClient) -> None:
    response = served.get(CLIENT_ROUTE, headers=NAVIGATING)
    assert response.status_code == 200
    assert response.text == SHELL
    assert served.head(CLIENT_ROUTE, headers=NAVIGATING).status_code == 200


def test_a_fetch_for_a_client_route_is_answered_with_the_problem_document(served: TestClient) -> None:
    response = served.get(CLIENT_ROUTE, headers={"Accept": "*/*"})
    assert response.status_code == 404
    assert response.json()["status"] == 404


def test_a_request_naming_no_media_type_at_all_is_not_a_navigation(served: TestClient) -> None:
    response = served.get("/an-image-the-page-forgot.png", headers={"Accept": ""})
    assert response.status_code == 404
    assert response.json()["status"] == 404


def test_an_api_refusal_on_a_write_keeps_its_problem_document(served: TestClient) -> None:
    response = served.delete("/api/v1/tokens/never-minted", headers=NAVIGATING)
    assert response.status_code == 404
    assert response.json()["detail"] == "no live token named 'never-minted'"


def test_a_write_to_a_client_route_is_not_answered_with_the_shell(served: TestClient) -> None:
    response = served.post(CLIENT_ROUTE, json={}, headers=NAVIGATING)
    assert response.status_code in (404, 405)
    assert not response.headers["content-type"].startswith("text/html")


def test_an_unknown_api_path_stays_a_problem_document(served: TestClient) -> None:
    response = served.get("/api/v1/nonexistent")
    assert response.status_code == 404
    assert response.json()["title"] == "Not Found"
    assert response.json()["instance"] == "/api/v1/nonexistent"


def test_the_shell_never_answers_for_the_configured_api_prefix(
    settings: Settings, admin_token: str, bundle: Path
) -> None:
    moved = settings.model_copy(update={"api_prefix": "/api/v2"})
    with TestClient(create_app(moved), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        assert client.get("/api/v2/nonexistent").json()["status"] == 404
        assert client.get("/config.json").json()["api_prefix"] == "/api/v2"


def test_the_probes_and_the_api_are_untouched_by_the_bundle(served: TestClient) -> None:
    assert served.get("/health").json()["status"] == "ok"
    assert served.get("/health/ready").json()["status"] == "healthy"
    assert served.get("/api/v1/system/info").json()["name"] == "dirigent"
    assert served.get("/api/v1/pipelines").json()["items"] == []
    assert served.post("/hooks/not-a-token", json={}).status_code == 404


def test_the_bundle_reads_this_instance_from_the_config_document(served: TestClient) -> None:
    response = served.get("/config.json")
    assert response.status_code == 200
    assert response.json() == {"api_prefix": "/api/v1", "version": __version__}
    assert response.headers["cache-control"] == "no-cache"


def test_the_icon_a_browser_asks_for_is_served(served: TestClient) -> None:
    assert served.get("/favicon.ico").status_code == 200


def test_a_bundle_carrying_no_icon_is_a_refusal_rather_than_the_shell(bundle: Path, served: TestClient) -> None:
    (bundle / "favicon.ico").unlink()
    response = served.get("/favicon.ico")
    assert response.status_code == 404
    assert response.json()["status"] == 404


def test_an_unbuilt_bundle_refuses_the_root_by_naming_the_command(unbuilt: TestClient) -> None:
    response = unbuilt.get("/")
    assert response.status_code == 503
    assert "make ui" in response.text
    assert response.headers["content-type"].startswith("text/plain")


def test_an_unbuilt_bundle_leaves_every_route_as_it_was(unbuilt: TestClient) -> None:
    assert unbuilt.get("/health").json()["status"] == "ok"
    assert unbuilt.get("/api/v1/system/info").json()["name"] == "dirigent"
    assert unbuilt.get("/api/v1/pipelines").json()["items"] == []
    assert unbuilt.get("/api/v1/nonexistent").json()["status"] == 404
    assert unbuilt.get("/assets/app-abc123.js").json()["status"] == 404
    assert unbuilt.post("/hooks/not-a-token", json={}).status_code == 404


def test_an_unbuilt_bundle_refuses_a_navigation_the_way_it_refuses_the_root(unbuilt: TestClient) -> None:
    """A person deep-linking into a UI that is switched on but not built hears why."""
    answer = unbuilt.get("/runs/anything", headers=NAVIGATING)
    assert answer.status_code == 503
    assert "make ui" in answer.text
    assert unbuilt.get("/runs/anything").json()["status"] == 404, "a fetch keeps its problem document"


def test_a_bundle_built_after_startup_is_served_without_a_restart(
    settings: Settings, admin_token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The index is a per-request question, so `make ui` lands under a running server."""
    monkeypatch.setattr(ui, "PACKAGED_STATIC", tmp_path / "never-installed")
    monkeypatch.setattr(ui, "CHECKOUT_STATIC", tmp_path / "dist")
    with TestClient(create_app(settings), headers={"Authorization": f"Bearer {admin_token}"}) as client:
        assert client.get("/").status_code == 503, "nothing is built yet"
        (tmp_path / "dist" / "assets").mkdir(parents=True)
        (tmp_path / "dist" / "index.html").write_text("<!doctype html><title>dirigent</title>")
        (tmp_path / "dist" / "assets" / "app-abc123.js").write_text("export {}")
        shell = client.get("/")
        assert shell.status_code == 200
        assert "dirigent" in shell.text
        asset = client.get("/assets/app-abc123.js")
        assert asset.status_code == 200
        assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
        (tmp_path / "dist" / "index.html").unlink()
        mid_rebuild = client.get("/runs/anything", headers=NAVIGATING)
        assert mid_rebuild.status_code == 503, "a rebuild's empty moment refuses rather than erroring"


def test_an_unbuilt_bundle_still_answers_the_config_document(unbuilt: TestClient) -> None:
    assert unbuilt.get("/config.json").json() == {"api_prefix": "/api/v1", "version": __version__}


def test_a_disabled_ui_serves_nothing_of_it_although_a_bundle_is_installed(api_only: TestClient) -> None:
    assert api_only.get("/").status_code == 404
    assert api_only.get("/config.json").json()["status"] == 404
    assert api_only.get(f"/{ASSET}").json()["status"] == 404
    assert api_only.get("/runs/anything", headers=NAVIGATING).json()["status"] == 404
    assert api_only.get("/health").json()["status"] == "ok"
    assert api_only.get("/api/v1/pipelines").json()["items"] == []


def test_the_static_directory_is_the_installed_one_before_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    installed = tmp_path / "installed"
    checkout = tmp_path / "checkout"
    for directory in (installed, checkout):
        directory.mkdir()
        (directory / "index.html").write_text(SHELL)
    monkeypatch.setattr(ui, "PACKAGED_STATIC", installed)
    monkeypatch.setattr(ui, "CHECKOUT_STATIC", checkout)
    assert ui.static_dir(settings) == installed
    monkeypatch.setattr(ui, "PACKAGED_STATIC", tmp_path / "absent")
    assert ui.static_dir(settings) == checkout
    assert ui.static_dir(settings.model_copy(update={"ui_enabled": False})) is None


def test_a_configured_ui_dir_is_served_before_anything_installed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    installed = tmp_path / "installed"
    named = tmp_path / "named"
    for directory in (installed, named):
        directory.mkdir()
        (directory / "index.html").write_text(SHELL)
    monkeypatch.setattr(ui, "PACKAGED_STATIC", installed)
    monkeypatch.setattr(ui, "CHECKOUT_STATIC", tmp_path / "absent")
    assert ui.static_dir(settings.model_copy(update={"ui_dir": named})) == named
    assert ui.static_dir(settings.model_copy(update={"ui_dir": tmp_path / "empty"})) is None, (
        "a named directory with no bundle serves nothing rather than falling back"
    )
