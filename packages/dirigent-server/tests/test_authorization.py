"""The three roles at the boundary: what a viewer may read, and what only an operator may write.

The parametrised list below is every state-changing route the API mounts that is not admin-only.
A test walks the mounted routes and refuses to let that list fall behind, so a new write route
added without a role decision fails here rather than shipping open.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import BaseRoute

from dirigent_server.routes import build_router
from dirigent_server.security import require_admin, require_operator
from tests_support import DOCUMENT, PASSWORD, apply_document

PREFIX = "/api/v1"

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Writes an operator may make. A viewer is refused before the handler runs, so a path here may
#: name a schedule or a run that does not exist.
OPERATOR_ONLY = [
    ("post", "/pipelines/$apply"),
    ("post", "/pipelines/$prune"),
    ("post", "/pipelines/api-demo/$activate"),
    ("post", "/pipelines/api-demo/$deactivate"),
    ("post", "/pipelines/api-demo/$run"),
    ("post", "/pipelines/api-demo/$backfill"),
    ("post", "/runs/00000000-0000-0000-0000-000000000000/$cancel"),
    ("post", "/attempts/00000000-0000-0000-0000-000000000000/$retry"),
    ("post", "/pipelines/api-demo/triggers/schedules"),
    ("patch", "/pipelines/api-demo/triggers/schedules/nightly"),
    ("post", "/pipelines/api-demo/triggers/schedules/nightly/$pause"),
    ("post", "/pipelines/api-demo/triggers/schedules/nightly/$resume"),
    ("delete", "/pipelines/api-demo/triggers/schedules/nightly"),
    ("post", "/pipelines/api-demo/triggers/webhooks"),
    ("post", "/pipelines/api-demo/triggers/webhooks/intake/$rotate-token"),
    ("post", "/pipelines/api-demo/triggers/webhooks/intake/$disable"),
    ("post", "/pipelines/api-demo/triggers/webhooks/intake/$enable"),
    ("delete", "/pipelines/api-demo/triggers/webhooks/intake"),
    ("delete", "/trigger-documents/nightly-clocks"),
    ("post", "/alert-rules"),
    ("patch", "/alert-rules/whatever"),
    ("delete", "/alert-rules/whatever"),
    ("post", "/alert-rules/$test"),
    ("post", "/notifications/00000000-0000-0000-0000-000000000000/$retry"),
]

#: Reads a viewer may make, next to the writes above.
VIEWER_ALLOWED = [
    "/pipelines",
    "/runs",
    "/connections",
    "/schemas",
    "/alert-rules",
    "/trigger-documents",
    "/notifications",
    "/blocks",
    "/workers",
    "/system/info",
    "/auth/me",
]

#: Unsafe-method routes that stay open to a viewer: two act on the caller's own credential, one
#: hands one out, one reports what a stored version would fail on, and one is arithmetic over a
#: clock in the body. None of them writes anything.
READ_SHAPED_WRITES = {
    "/auth/login",
    "/auth/logout",
    "/auth/password",
    "/pipelines/{code}/$validate",
    "/schedules/$preview",
}


def api_routes(routes: Any = None) -> Iterator[APIRoute]:
    """Every route the versioned router mounts, including those a nested router contributed."""
    for route in build_router().routes if routes is None else routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        nested: list[BaseRoute] = getattr(getattr(route, "original_router", None), "routes", [])
        yield from api_routes(nested)


def writes() -> Iterator[tuple[str, APIRoute]]:
    for route in api_routes():
        for method in sorted(set(route.methods or ()) & UNSAFE_METHODS):
            yield method, route


def guards(dependant: Dependant, call: Any) -> bool:
    """Whether a route resolves through this role dependency, however deeply it is nested."""
    return any(sub.call is call or guards(sub, call) for sub in dependant.dependencies)


def test_every_write_route_names_a_role() -> None:
    """A write route added without a role decision is caught here, not by a viewer in production."""
    open_to_a_viewer = [
        f"{method} {route.path}"
        for method, route in writes()
        if route.path not in READ_SHAPED_WRITES
        and not guards(route.dependant, require_admin)
        and not guards(route.dependant, require_operator)
    ]
    assert open_to_a_viewer == []


def test_the_operator_only_list_covers_every_such_route() -> None:
    """The parametrised list is the whole operator-only surface, so its coverage is complete."""
    mounted = [f"{method} {route.path}" for method, route in writes() if guards(route.dependant, require_operator)]
    assert len(OPERATOR_ONLY) == len(mounted)


@pytest.mark.parametrize(("method", "path"), OPERATOR_ONLY)
def test_a_viewer_may_not_write(viewer: TestClient, method: str, path: str) -> None:
    """Every state-changing route that is not admin-only refuses a viewer."""
    response = viewer.request(method, f"{PREFIX}{path}", json={})
    assert response.status_code == 403, f"{method} {path} let a viewer through"
    assert "not permitted for your role" in response.json()["detail"]


@pytest.mark.parametrize("path", VIEWER_ALLOWED)
def test_a_viewer_may_read(viewer: TestClient, path: str) -> None:
    """The same account reads every listing the UI shows."""
    response = viewer.get(f"{PREFIX}{path}")
    assert response.status_code == 200, response.text


def test_a_viewer_reads_a_pipeline_a_run_and_a_report(client: TestClient, viewer: TestClient) -> None:
    """Applying and running is an operator's; reading what it produced is a viewer's."""
    apply_document(client, DOCUMENT)
    started = client.post(f"{PREFIX}/pipelines/api-demo/$run", json={})
    assert started.status_code == 202, started.text
    run_id = started.json()["run_id"]

    assert viewer.get(f"{PREFIX}/pipelines/api-demo").status_code == 200
    assert viewer.get(f"{PREFIX}/pipelines/api-demo/$export").status_code == 200
    assert viewer.get(f"{PREFIX}/runs/{run_id}").status_code == 200
    assert viewer.get(f"{PREFIX}/runs/{run_id}/$report").status_code == 200
    assert viewer.post(f"{PREFIX}/pipelines/api-demo/$validate", json={}).status_code == 200


def test_a_viewer_may_change_its_own_password(viewer: TestClient) -> None:
    """A route that acts on the caller's own credential is not an operator's privilege."""
    response = viewer.post(
        f"{PREFIX}/auth/password",
        json={"current_password": PASSWORD, "new_password": "another test password"},
    )
    assert response.status_code == 204, response.text


def test_an_operator_applies_runs_schedules_and_cancels(operator: TestClient) -> None:
    """The writes a viewer was refused all succeed for an operator."""
    assert apply_document(operator, DOCUMENT)["plan"]["action"] == "create"

    schedule = operator.post(
        f"{PREFIX}/pipelines/api-demo/triggers/schedules",
        json={"code": "nightly", "cron": "0 2 * * *", "timezone": "UTC"},
    )
    assert schedule.status_code == 201, schedule.text

    started = operator.post(f"{PREFIX}/pipelines/api-demo/$run", json={"params": {"greeting": "hei"}})
    assert started.status_code == 202, started.text

    cancelled = operator.post(f"{PREFIX}/runs/{started.json()['run_id']}/$cancel")
    assert cancelled.status_code == 200, cancelled.text


def test_an_operator_is_still_refused_an_admin_route(operator: TestClient) -> None:
    """The operator rung stops where handing out authority begins."""
    response = operator.post(f"{PREFIX}/tokens", json={"name": "mine"})
    assert response.status_code == 403
    assert "not permitted for your role" in response.json()["detail"]
