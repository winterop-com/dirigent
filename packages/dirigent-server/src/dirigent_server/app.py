"""The FastAPI application factory."""

import asyncio
import contextlib
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from dirigent_core import __version__
from dirigent_core.auth import BOOTSTRAP_PASSWORD_ENV, bootstrap_admin
from dirigent_core.config import Settings, get_settings
from dirigent_core.database import create_engine, create_session_factory, session_scope
from dirigent_core.directory import apply_directory
from dirigent_core.engine.services import EngineServices
from dirigent_core.plugins import PluginHost, load_plugin_host
from dirigent_core.scheduler import Scheduler
from dirigent_core.telemetry import configure_telemetry, instrument_fastapi
from dirigent_server.errors import install_error_handlers
from dirigent_server.health import build_registry
from dirigent_server.health import router as health_router
from dirigent_server.logging import get_logger
from dirigent_server.routes import TAGS, build_hooks_router, build_router
from dirigent_server.security import install_cross_site_guard
from dirigent_server.ui import mount_ui_assets, mount_ui_shell

DESCRIPTION = """
A generic pipeline orchestrator. Pipelines are data, composed from pluggable building
blocks and executed as a DAG on a durable engine.

Every endpoint under `/api/v1` requires authentication: a bearer token for automation, or
the session cookie `POST /api/v1/auth/login` sets for a browser. The probes under `/health`
and this document itself are the only exceptions. `POST /hooks/{token}` is outside the
versioned API and authenticates with its own per-trigger token.
"""

_logger = get_logger("server")

BOOTSTRAP_ENV = BOOTSTRAP_PASSWORD_ENV
SCHEDULER_STOP_SECONDS = 10.0


def create_app(
    settings: Settings | None = None,
    *,
    host: PluginHost | None = None,
    scheduler: bool | None = None,
) -> FastAPI:
    """Build the API application: health probes, the routers, the UI, and the embedded scheduler.

    Scheduler leadership is an advisory lock, so running the scheduler here, in a dedicated
    ``dg scheduler``, or in both at once is safe.

    The UI mounts in two pieces around the routers: its fixed paths before them, its shell
    after them, so an API route is matched before anything the bundle claims.
    """
    resolved = settings or get_settings()
    embed = resolved.scheduler_enabled if scheduler is None else scheduler
    configure_telemetry(resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
        """Open the database engine for the process, and dispose of it on shutdown."""
        engine = create_engine(resolved)
        app.state.engine = engine
        app.state.session_factory = create_session_factory(engine)
        app.state.health_checks = build_registry(engine)
        await _bootstrap(app)
        await _apply_startup_directory(app)
        clock = await _start_scheduler(app, embed=embed)
        _logger.info(
            "server starting",
            database="sqlite" if resolved.is_sqlite else "postgresql",
            blocks=len(app.state.services.host.block_ids),
            scheduler=embed,
        )
        try:
            yield
        finally:
            await _stop_scheduler(app, clock)
            await engine.dispose()
            _logger.info("server stopped")

    app = FastAPI(
        title="dirigent",
        summary="A generic pipeline orchestrator.",
        description=DESCRIPTION.strip(),
        version=__version__,
        openapi_tags=TAGS,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.version = __version__
    app.state.services = EngineServices.build(resolved, host or load_plugin_host())
    install_cross_site_guard(app, resolved)
    install_error_handlers(app)
    mount_ui_assets(app, resolved)
    app.include_router(health_router)
    app.include_router(build_hooks_router())
    app.include_router(build_router(), prefix=resolved.api_prefix)
    mount_ui_shell(app, resolved)
    instrument_fastapi(app)
    return app


async def _start_scheduler(app: FastAPI, *, embed: bool) -> asyncio.Task[None] | None:
    """Start the embedded scheduler as a task in the API's own event loop."""
    app.state.scheduler = None
    if not embed:
        return None
    scheduler = Scheduler(app.state.session_factory, app.state.services)
    app.state.scheduler = scheduler
    return asyncio.create_task(scheduler.run())


async def _stop_scheduler(app: FastAPI, task: asyncio.Task[None] | None) -> None:
    """Ask the embedded scheduler to finish its tick and hand back leadership."""
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler is not None:
        scheduler.request_stop()
    if task is not None:
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(task, timeout=SCHEDULER_STOP_SECONDS)


async def _apply_startup_directory(app: FastAPI) -> None:
    """Apply the configured directory of schemas and documents, before the scheduler starts firing.

    The summary is one record; each refused file has already said its own warning. A
    boot that found the lock held skips quietly: whoever holds it is doing this work.
    """
    settings: Settings = app.state.settings
    if settings.apply_dir is None:
        return
    summary = await apply_directory(
        app.state.session_factory,
        app.state.services,
        settings.apply_dir,
        prune=settings.apply_prune,
        lock_key=settings.apply_lock_key,
    )
    if summary.skipped:
        return
    _logger.info(
        "startup directory applied",
        directory=str(settings.apply_dir),
        applied=len(summary.applied),
        updated=len(summary.updated),
        unchanged=len(summary.unchanged),
        schemas=len(summary.schemas),
        refused=[refusal.code or refusal.path for refusal in summary.refused],
        pruned=summary.pruned,
        trigger_documents_removed=summary.trigger_documents_removed,
    )


async def _bootstrap(app: FastAPI) -> None:
    """Create the first admin when a container names a password and no account exists yet.

    Does nothing once any account exists, so leaving the variable set on every deploy
    cannot reset a live instance's admin password.
    """
    import os

    password = os.environ.get(BOOTSTRAP_ENV)
    if not password:
        return
    async with session_scope(app.state.session_factory) as session:
        created = await bootstrap_admin(session, password)
    if created is not None:
        _logger.info("bootstrap admin created", username=created.username)
