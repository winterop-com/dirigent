"""FastAPI dependencies: the request session, the engine services, and the settings."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_core.config import Settings
from dirigent_core.engine.services import EngineServices


def get_settings(request: Request) -> Settings:
    """Return the settings this application was built with."""
    resolved: Settings = request.app.state.settings
    return resolved


def get_services(request: Request) -> EngineServices:
    """Return the engine services: the plugin host, storage, and the secret box."""
    services: EngineServices = request.app.state.services
    return services


def get_sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    """Return the session factory the API and the engine share."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    return factory


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """Open one transaction for one request, and hand it to the route to commit.

    The exit of a dependency that yields runs after the response has gone out, so committing
    here tells a client its write happened before it had: a client that reads straight back
    can miss what it just wrote, and a commit that fails does so after a 2xx. ``Transactional``
    commits while the response can still change. This only has to undo one that did not get
    there.
    """
    async with get_sessions(request)() as session:
        request.state.session = session
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise


SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[EngineServices, Depends(get_services)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
