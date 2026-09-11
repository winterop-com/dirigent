"""The client itself: one connection, and one namespaced accessor per API resource."""

import asyncio
import threading
from collections.abc import AsyncIterator, Awaitable, Iterator, Mapping
from typing import Any, Self

import httpx2

from dirigent_client.resources.alerts import Alerts
from dirigent_client.resources.auth import Admin, Auth
from dirigent_client.resources.blocks import Blocks
from dirigent_client.resources.connections import Connections
from dirigent_client.resources.examples import Examples
from dirigent_client.resources.pipelines import Pipelines
from dirigent_client.resources.runs import Runs
from dirigent_client.resources.schedules import Schedules
from dirigent_client.resources.schemas import Schemas
from dirigent_client.resources.system import System, Workers
from dirigent_client.resources.trigger_documents import TriggerDocuments
from dirigent_client.resources.webhooks import Webhooks
from dirigent_client.transport import API_PREFIX, DEFAULT_RETRIES, DEFAULT_TIMEOUT, Transport

SHUTDOWN_SECONDS = 5.0


class Dirigent:
    """An authenticated connection to one dirigent instance."""

    def __init__(
        self,
        *,
        url: str,
        token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        headers: Mapping[str, str] | None = None,
        http_transport: httpx2.AsyncBaseTransport | None = None,
        api_prefix: str = API_PREFIX,
    ) -> None:
        """Open a connection to an instance, with a bearer token when one is needed."""
        self.transport = Transport(
            url=url,
            api_prefix=api_prefix,
            token=token,
            timeout=timeout,
            retries=retries,
            headers=headers,
            http_transport=http_transport,
        )
        self.pipelines = Pipelines(self.transport)
        self.runs = Runs(self.transport)
        self.connections = Connections(self.transport)
        self.schemas = Schemas(self.transport)
        self.blocks = Blocks(self.transport)
        self.examples = Examples(self.transport)
        self.schedules = Schedules(self.transport)
        self.webhooks = Webhooks(self.transport)
        self.trigger_documents = TriggerDocuments(self.transport)
        self.alerts = Alerts(self.transport)
        self.system = System(self.transport)
        self.workers = Workers(self.transport)
        self.auth = Auth(self.transport)
        self.admin = Admin(self.transport)

    @property
    def url(self) -> str:
        """Name the instance this client is bound to."""
        return self.transport.url

    async def __aenter__(self) -> Self:
        """Enter the client's context."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Close the underlying connection pool."""
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying connection pool."""
        await self.transport.aclose()


class BlockingDirigent:
    """The same client, driven from synchronous code."""

    def __init__(self, **kwargs: Any) -> None:
        """Open a connection and the loop its calls run on; the arguments are Dirigent's."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="dirigent-client", daemon=True)
        self._thread.start()
        self.client = Dirigent(**kwargs)
        self.url = self.client.url
        self.pipelines = self.client.pipelines
        self.runs = self.client.runs
        self.connections = self.client.connections
        self.schemas = self.client.schemas
        self.blocks = self.client.blocks
        self.examples = self.client.examples
        self.schedules = self.client.schedules
        self.webhooks = self.client.webhooks
        self.trigger_documents = self.client.trigger_documents
        self.alerts = self.client.alerts
        self.system = self.client.system
        self.workers = self.client.workers
        self.auth = self.client.auth
        self.admin = self.client.admin

    def __enter__(self) -> Self:
        """Enter the client's context."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the connection pool and stop the loop."""
        self.close()

    def call[T](self, awaitable: Awaitable[T]) -> T:
        """Run one of the client's coroutines to completion and return what it produced."""
        return asyncio.run_coroutine_threadsafe(_awaited(awaitable), self._loop).result()

    def iterate[T](self, source: AsyncIterator[T]) -> Iterator[T]:
        """Read an async iterator, such as a log tail, as an ordinary one."""
        while True:
            try:
                yield self.call(anext(source))
            except StopAsyncIteration:
                return

    def close(self) -> None:
        """Close the connection pool and stop the loop it was running on.

        The asynchronous generators must be shut down before the loop is: a generator
        finalised after its loop has closed raises where nobody is listening.
        """
        try:
            self.call(self.client.aclose())
            self.call(self._loop.shutdown_asyncgens())
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=SHUTDOWN_SECONDS)
            self._loop.close()


async def _awaited[T](awaitable: Awaitable[T]) -> T:
    """Wrap an awaitable as the coroutine ``run_coroutine_threadsafe`` requires."""
    return await awaitable
