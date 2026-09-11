"""The versioned API, assembled from one router per resource.

Every business router is mounted behind :func:`require_principal`, so authentication is a
property of the mount. Only login is exempt. Webhook intake authenticates as the trigger
rather than as a person, so it is mounted at the application root instead.
"""

from fastapi import APIRouter, Depends

from dirigent_server.routes import (
    alerts,
    auth,
    blocks,
    connections,
    examples,
    hooks,
    pipelines,
    runs,
    schema,
    schemas,
    system,
    trigger_documents,
    triggers,
    users,
    workers,
)
from dirigent_server.security import require_principal
from dirigent_server.transactions import Transactional

TAGS: list[dict[str, str]] = [
    {"name": "auth", "description": "Logging in, and the tokens automation uses."},
    {"name": "pipelines", "description": "Applying, exporting, and running definitions."},
    {"name": "runs", "description": "Runs, their attempts, their logs, and their reports."},
    {"name": "triggers", "description": "A pipeline's schedules and inbound webhooks."},
    {"name": "alerts", "description": "Alert rules, and the queue they deliver through."},
    {"name": "hooks", "description": "Webhook intake, authenticated by its own token."},
    {"name": "connections", "description": "Named credential records of contributed kinds."},
    {"name": "blocks", "description": "The catalog every plugin contributes to."},
    {"name": "examples", "description": "The documents every installed plugin ships."},
    {"name": "schema", "description": "The shape a document is written against."},
    {"name": "schemas", "description": "Named JSON Schemas the instance holds."},
    {"name": "workers", "description": "The worker registry."},
    {"name": "users", "description": "Local accounts."},
    {"name": "system", "description": "What this instance is, and whether it is well."},
    {"name": "health", "description": "Liveness and readiness."},
]


def build_router() -> APIRouter:
    """Assemble the versioned API: the login route, then everything behind authentication."""
    router = APIRouter(route_class=Transactional)
    router.include_router(auth.public_router)
    guarded = APIRouter(dependencies=[Depends(require_principal)], route_class=Transactional)
    for module in (
        auth,
        pipelines,
        triggers,
        trigger_documents,
        runs,
        alerts,
        connections,
        blocks,
        examples,
        schema,
        schemas,
        workers,
        users,
        system,
    ):
        guarded.include_router(module.router)
    router.include_router(guarded)
    return router


def build_hooks_router() -> APIRouter:
    """Assemble the unauthenticated webhook intake, mounted at the application root."""
    router = APIRouter(route_class=Transactional)
    router.include_router(hooks.router)
    return router


__all__ = ["TAGS", "build_hooks_router", "build_router"]
