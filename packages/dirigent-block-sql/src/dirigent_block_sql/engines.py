"""The engine contract the ``sql`` family drives a database through, and the registry of engines.

An engine is one backend -- what a URL's scheme names -- and the decisions that differ from one
backend to the next: what makes a connection to it valid, where a database written as a relative
path lands, what a parameter has to become before the database sees it, how a check reaches it,
and what a session on it is. Everything else about ``sql.query`` and ``sql.execute`` is the same
whichever engine answers.

Any dialect with an async driver is the generic path here, and a backend that needs more than a
driver -- DuckDB, which has no async driver at all -- is a package contributing an engine under
the ``dirigent.sql.engines.v1`` entry-point group. A block cannot reach the plugin host, so the
family loads that group itself, once per process.
"""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from functools import cache
from typing import TYPE_CHECKING, Any, ClassVar, Final, Protocol

import sqlalchemy
import sqlalchemy.exc
from pluginkit import PluginManager
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.sql.elements import TextClause

from dirigent_block_sql import markers
from dirigent_block_sql.markers import ENGINES_GROUP
from dirigent_block_sql.messages import (
    CONNECT_TIMED_OUT,
    DRIVER_NOT_INSTALLED,
    ENGINE_PACKAGE_MISSING,
    NO_ASYNC_DRIVER,
    READ_ONLY_UNSUPPORTED,
)
from dirigent_common import HealthReport, JsonMap
from dirigent_plugin import PROJECT_NAME, BlockFailure, ErrorClass, StepContext

if TYPE_CHECKING:
    from dirigent_block_sql.sql import SqlConnectionConfig

#: How long a connection check may spend reaching the database and asking it for a one.
CHECK_TIMEOUT_SECONDS = 30.0

#: What a check answers for a database file that exists only while a run is on the worker.
OUTSIDE_A_RUN: Final = (
    "a database file relative to a run's work directory exists only inside a run, so there is nothing here to check"
)

#: The dialects whose sessions can be made read-only, and how each one is told.
READ_ONLY: Final = {
    "postgresql": "SET TRANSACTION READ ONLY",
    "sqlite": "PRAGMA query_only = 1",
}

#: The distribution that provides each async driver a URL can name, for the install line an
#: absent one is refused with.
DRIVER_PACKAGE: Final = {
    "aiosqlite": "aiosqlite",
    "asyncpg": "asyncpg",
    "psycopg": "psycopg[binary]",
    "aiomysql": "aiomysql",
    "asyncmy": "asyncmy",
    "aioodbc": "aioodbc",
    "aiooracle": "aiooracle",
    "oracledb": "oracledb",
}

#: The package each backend that is an engine rather than a driver is carried by, for the
#: install line a URL naming one is refused with when it is not installed.
KNOWN_ENGINE_PACKAGES: Final = {"duckdb": "dirigent-block-sql-duckdb"}


class DuplicateEngine(Exception):
    """Two plugins claimed the same backend."""

    def __init__(self, backend: str, first: str, second: str) -> None:
        """Name the backend and both plugins."""
        super().__init__(
            f"backend {backend!r} is contributed by both {first!r} and {second!r}, and a backend is what a "
            f"connection's url dispatches on, so one of the two packages must be uninstalled."
        )
        self.backend = backend
        self.plugins = (first, second)


class SqlSession(Protocol):
    """The connection surface both blocks drive, whichever engine opened it."""

    async def execute(self, statement: TextClause, parameters: dict[str, Any] | None = None, /) -> Any:
        """Run one statement and hand back its result, rowcount included."""
        ...

    def stream(self, statement: TextClause, parameters: dict[str, Any] | None = None, /) -> Awaitable[Any]:
        """Run one statement and hand back a cursor read a batch at a time.

        Awaited rather than declared ``async`` because SQLAlchemy's own is a context manager
        that is also awaitable, and a step awaits it.
        """
        ...

    def begin(self) -> AbstractAsyncContextManager[Any]:
        """One transaction, committed when the block leaves cleanly and rolled back otherwise."""
        ...


class SqlEngine(ABC):
    """One backend of the ``sql`` family: what a URL naming it means, and how a step drives it."""

    backend: ClassVar[str]
    """The backend a URL names this engine by, as ``URL.get_backend_name()`` spells it."""

    @abstractmethod
    def validate(self, settings: "SqlConnectionConfig", url: URL) -> None:
        """Refuse a connection this engine cannot open, saying what about it is refused."""

    def resolve(self, url: URL, ctx: StepContext) -> URL:
        """The URL a step connects with, for an engine whose database may be a file of the run."""
        return url

    def bind(self, params: JsonMap, ctx: StepContext) -> dict[str, Any]:
        """The parameters as this engine receives them."""
        return dict(params)

    @abstractmethod
    async def check(self, settings: "SqlConnectionConfig", url: URL) -> HealthReport:
        """Reach the database and ask it for a one, which is the smallest proof of reach and credential."""

    @abstractmethod
    def session(
        self,
        settings: "SqlConnectionConfig",
        url: URL,
        ctx: StepContext,
        *,
        statements: Sequence[str],
        params: JsonMap,
    ) -> AbstractAsyncContextManager[SqlSession]:
        """The session a step runs its statements in, opened on entry and closed on exit.

        The statements and the bound parameters are handed over whole, because what a session
        has to be given -- a scheme's credentials, an extension -- is read off what will run in
        it.
        """


class SqlAlchemyEngine(SqlEngine):
    """Any dialect with an async driver, driven through SQLAlchemy's own asyncio layer."""

    #: It answers for every backend no installed engine claims, so it is registered under none.
    backend: ClassVar[str] = ""

    def validate(self, settings: "SqlConnectionConfig", url: URL) -> None:
        """Refuse a URL naming no async driver, and ``read_only`` on a dialect that has no mode for it."""
        backend = url.get_backend_name()
        if "+" not in url.drivername:
            package = KNOWN_ENGINE_PACKAGES.get(backend)
            if package is not None:
                raise ValueError(ENGINE_PACKAGE_MISSING.render(backend=backend, package=package))
            raise ValueError(NO_ASYNC_DRIVER.render(driver=repr(url.drivername), driver_name=url.drivername))
        if settings.read_only and backend not in READ_ONLY:
            supported = ", ".join(sorted(READ_ONLY))
            raise ValueError(READ_ONLY_UNSUPPORTED.render(backend=backend, supported=supported))

    def resolve(self, url: URL, ctx: StepContext) -> URL:
        """A sqlite database written as a relative path is a file in the run's work directory."""
        return under_work(url, ctx) if _is_run_relative(url) else url

    async def check(self, settings: "SqlConnectionConfig", url: URL) -> HealthReport:
        """Open a connection and run ``SELECT 1`` over the driver the URL names."""
        if _is_run_relative(url):
            return HealthReport(healthy=False, detail=OUTSIDE_A_RUN)
        try:
            engine = _engine(url)
        except BlockFailure as error:
            return HealthReport(healthy=False, detail=str(error))
        try:
            async with asyncio.timeout(CHECK_TIMEOUT_SECONDS), engine.connect() as connection:
                await connection.execute(sqlalchemy.text("SELECT 1"))
        except (TimeoutError, sqlalchemy.exc.SQLAlchemyError, OSError) as error:
            return HealthReport(healthy=False, detail=reason(error))
        finally:
            await engine.dispose()
        return HealthReport(healthy=True, detail=f"{url.get_backend_name()} answered")

    def session(
        self,
        settings: "SqlConnectionConfig",
        url: URL,
        ctx: StepContext,
        *,
        statements: Sequence[str],
        params: JsonMap,
    ) -> AbstractAsyncContextManager[SqlSession]:
        """One async connection, put in the mode the connection kind asked for."""
        return _Session(settings, url)


#: The engine a backend no installed package claims is driven through.
GENERIC: Final = SqlAlchemyEngine()


def under_work(url: URL, ctx: StepContext) -> URL:
    """The same URL with its database file placed under the run's own work directory."""
    database = ctx.work / str(url.database)
    database.parent.mkdir(parents=True, exist_ok=True)
    return url.set(database=str(database))


def reason(error: Exception) -> str:
    """The one sentence a health report gives for a database that did not answer."""
    if isinstance(error, TimeoutError):
        return f"no answer within {CHECK_TIMEOUT_SECONDS:.0f}s"
    text = str(getattr(error, "orig", None) or error).strip().splitlines()
    return text[0] if text else type(error).__name__


def registry(
    *,
    group: str = ENGINES_GROUP,
    extra: Mapping[str, object] | None = None,
) -> dict[str, SqlEngine]:
    """Build the registry: the engine every installed plugin contributes, keyed by backend.

    ``extra`` registers plugin objects that are not installed as distributions.
    """
    found: dict[str, SqlEngine] = {}
    origins: dict[str, str] = {}
    manager = PluginManager(PROJECT_NAME)
    manager.add_extension_points(markers)
    manager.load_entrypoints(group)
    for name, plugin in (extra or {}).items():
        manager.register(plugin, name=name)
    # The hook's return annotation is a declaration, not an enforcement: a plugin may answer
    # with anything, and anything that is not an engine is not registered.
    for plugin_name, contributed in manager.caller(markers.engines).collect_with_plugins():
        for engine in contributed:
            if not isinstance(engine, SqlEngine):  # pyright: ignore[reportUnnecessaryIsInstance]
                continue
            owner = origins.get(engine.backend)
            if owner is not None:
                raise DuplicateEngine(engine.backend, owner, plugin_name)
            origins[engine.backend] = plugin_name
            found[engine.backend] = engine
    return found


@cache
def _installed() -> dict[str, SqlEngine]:
    """The engines this process found, scanned once: a step must not rescan for every statement."""
    return registry()


def engine_for(url: URL) -> SqlEngine:
    """The engine registered for this URL's backend, or the generic async SQLAlchemy one."""
    return _installed().get(url.get_backend_name(), GENERIC)


def _is_run_relative(url: URL) -> bool:
    """Whether this is a sqlite file named by a path relative to the run's work directory."""
    database = url.database or ""
    if url.get_backend_name() != "sqlite":
        return False
    return bool(database) and not database.startswith("/")


def _engine(url: URL) -> AsyncEngine:
    """Build the engine one step uses, naming the package to install when the driver is absent.

    ``NullPool`` because a step opens one connection and the worker process may run the next
    step against a different database entirely; a pool would outlive what it serves.
    """
    try:
        return create_async_engine(url, poolclass=NullPool)
    except (ModuleNotFoundError, sqlalchemy.exc.NoSuchModuleError) as error:
        driver = url.drivername.partition("+")[2]
        package = DRIVER_PACKAGE.get(driver, driver)
        raise BlockFailure(
            DRIVER_NOT_INSTALLED,
            error_class=ErrorClass.REJECTED,
            driver=repr(driver),
            package=repr(package),
            shipped=", ".join(["asyncpg", "aiosqlite"]),
        ) from error


class _Session:
    """One connection, opened under the connection's timeout and read-only where it says so."""

    def __init__(self, settings: "SqlConnectionConfig", url: URL) -> None:
        """Hold what opening this step's connection needs."""
        self.settings = settings
        self.url = url
        self.engine = _engine(url)
        self.connection: AsyncConnection | None = None

    async def __aenter__(self) -> AsyncConnection:
        """Open the connection and put it in the mode the connection kind asked for."""
        try:
            async with asyncio.timeout(self.settings.connect_timeout.total_seconds()):
                self.connection = await self.engine.connect()
        except TimeoutError as error:
            await self.engine.dispose()
            raise BlockFailure(
                CONNECT_TIMED_OUT, error_class=ErrorClass.TRANSIENT, timeout=self.settings.connect_timeout
            ) from error
        except BaseException:
            await self.engine.dispose()
            raise
        if self.settings.read_only:
            await self.connection.execute(sqlalchemy.text(READ_ONLY[self.url.get_backend_name()]))
        return self.connection

    async def __aexit__(self, *_error: object) -> None:
        """Close the connection and the engine behind it, however the step left."""
        if self.connection is not None:
            await self.connection.close()
        await self.engine.dispose()
