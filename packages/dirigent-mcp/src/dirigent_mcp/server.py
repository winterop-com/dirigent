"""The MCP server: one dirigent instance, operated by an agent through the instance's own API.

Every tool is a call the Python client already makes, so what an agent may do is bounded by
the role of the token it was given. No tool is a delete, but ``apply_document`` retires what a
document stops declaring: a source, with its input journal and its token, and a schedule the
document managed. Applying and running a document is still the whole of the instance's reach: a
pipeline the agent writes runs with every connection the instance holds. Read-only, the server
offers the reading tools alone.

Over stdio one client carries the token the environment names; over HTTP each call carries the
bearer token of the request it arrived on (see :mod:`dirigent_mcp.http`).
"""

import argparse
import os
import sys
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Any, Final, cast

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import TypeAdapter
from starlette.requests import Request

from dirigent_client import BlockKind, Dirigent, DirigentError, RunStatus
from dirigent_client.resources.pipelines import parse_document
from dirigent_common import JsonMap
from dirigent_common.hosts import is_loopback_host
from dirigent_mcp.messages import NO_HTTP_INSTANCE, NO_INSTANCE, REMOTE_BIND, REMOTE_BIND_REFUSED

#: Where the server finds its instance and its token, the names `dg` reads them from.
URL_ENV: Final = "DG_URL"
TOKEN_ENV: Final = "DG_TOKEN"

#: Set to a true value, the server offers only the tools that read.
READ_ONLY_ENV: Final = "DG_MCP_READ_ONLY"

#: Where the HTTP transport listens unless told otherwise.
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 3334

#: How many rows a listing answers with when the agent names no limit.
DEFAULT_LIMIT: Final = 50

#: The longest a run started with ``wait`` is waited on before its id is answered instead.
MAX_WAIT: Final = timedelta(minutes=10)

READS: Final = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES: Final = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
APPLIES: Final = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)
ANSWER: Final = TypeAdapter[Any](Any)

STOPS: Final = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)

INSTRUCTIONS: Final = """\
This server operates one dirigent instance: a data pipeline orchestrator whose pipelines are
YAML documents of steps, each step a block with a config. Before writing a document, read
the blocks it will use (list_blocks, get_block) and an example close to it (list_examples,
get_example); plan_document checks a document against the instance without storing it, and
lists under sources.removed and triggers.schedules_removed what applying it would retire.
apply_document retires a source, with its input journal and token, and a schedule when the
document stops declaring them, so plan first and keep every source and schedule a pipeline has.
A run is started with run_pipeline, read with get_run, run_logs and run_attempts, and run again with rerun_run."""


#: Opens the client one call is made through, and closes it after when it is that call's own.
Connect = Callable[[], AbstractAsyncContextManager[Dirigent]]

#: The HTTP request the message being handled arrived on; nothing over stdio.
ARRIVED_ON: ContextVar[Request | None] = ContextVar("dirigent_mcp_arrived_on", default=None)


def shared(open_client: Callable[[], Dirigent]) -> Connect:
    """One client for every call, opened on the first so it lives on the server's loop."""
    opened: list[Dirigent] = []

    @asynccontextmanager
    async def connect() -> AsyncGenerator[Dirigent]:
        if not opened:
            opened.append(open_client())
        yield opened[0]

    return connect


async def remember_request(ctx: ServerRequestContext[Any, Any], call_next: CallNext) -> HandlerResult:
    """Hold the HTTP request a message arrived on while it is handled, for a tool to read its credential."""
    request = ctx.request
    held = ARRIVED_ON.set(cast(Request, request) if isinstance(request, Request) else None)
    try:
        return await call_next(ctx)
    finally:
        ARRIVED_ON.reset(held)


def build(connect: Connect, *, read_only: bool = False) -> MCPServer:
    """Build the server whose tools call the instance through ``connect``, or only its reading ones."""
    server = MCPServer(name="dirigent", instructions=INSTRUCTIONS, log_level="WARNING", middleware=[remember_request])

    def tool[F: Callable[..., Any]](annotations: ToolAnnotations) -> Callable[[F], F]:
        """Register a tool, unless the server reads only and this tool writes."""
        if read_only and annotations is not READS:
            return lambda function: function
        return server.tool(annotations=annotations)

    async def call[T](work: Callable[[Dirigent], Awaitable[T]]) -> Any:
        """Make one call, answering with its JSON, and a refusal as a tool error the agent reads."""
        try:
            async with connect() as dg:
                answer = await work(dg)
        except DirigentError as error:
            raise ToolError(str(error)) from error
        return _json(answer)

    @tool(READS)
    async def instance_info() -> Any:
        """Describe the instance: its version, database, and how many blocks it has installed."""
        return await call(lambda dg: dg.system.info())

    @tool(READS)
    async def whoami() -> Any:
        """Say who these calls act as: the account, its role, and the name of the token presented."""
        return await call(lambda dg: dg.auth.whoami())

    @tool(READS)
    async def list_pipelines(
        tags: list[str] | None = None, after: str | None = None, limit: int = DEFAULT_LIMIT
    ) -> Any:
        """List the pipelines, optionally those carrying every tag given; pass `next` as `after` for more."""
        return await call(lambda dg: dg.pipelines.list(tags=tags or (), after=after, limit=limit))

    @tool(READS)
    async def get_pipeline(code: str) -> Any:
        """Read one pipeline: its current version, its document, and its schedules and sources."""
        return await call(lambda dg: dg.pipelines.get(code))

    @tool(READS)
    async def export_pipeline(code: str, version: int | None = None) -> Any:
        """Render a stored pipeline as the YAML document it was applied as, the current version unless one is named."""
        return await call(lambda dg: dg.pipelines.export(code, version=version))

    @tool(READS)
    async def validate_pipeline(code: str) -> Any:
        """Report what a stored pipeline would fail on if it ran now, such as a block gone missing."""

        async def checked(dg: Dirigent) -> Any:
            return {"issues": await dg.pipelines.validate(code)}

        return await call(checked)

    @tool(READS)
    async def plan_document(document: str) -> Any:
        """Check a YAML pipeline or triggers document against the instance without storing it.

        Answers what applying it would do, or every issue that refuses it. `sources.removed` and
        `triggers.schedules_removed` name what applying it would retire.
        """
        return await call(lambda dg: dg.pipelines.apply(parse_document(document), dry_run=True))

    @tool(APPLIES)
    async def apply_document(document: str, paused: bool = False) -> Any:
        """Store a YAML pipeline or triggers document as a new version; an unchanged one is left as it is.

        A source or a schedule the document managed and no longer declares is deleted, and a
        source's input journal and token go with it. plan_document names them first. `paused`
        creates the schedules and the polled or held sources this apply brings into being paused.
        """
        return await call(lambda dg: dg.pipelines.apply(parse_document(document), paused=paused))

    @tool(WRITES)
    async def run_pipeline(
        code: str,
        params: JsonMap | None = None,
        source: str | None = None,
        input: Any = None,
        wait: bool = False,
        timeout_seconds: int = 60,
    ) -> Any:
        """Start a run of a pipeline with its parameters, or for a pipeline with sources the input it enters with.

        With `wait`, answer once the run has settled or `timeout_seconds` has passed, whichever is first.
        """

        async def started(dg: Dirigent) -> Any:
            accepted = await dg.pipelines.run(code, params=params, source=source, input=input)
            if not wait or accepted.run_id is None:
                return accepted
            limit = min(timedelta(seconds=max(timeout_seconds, 1)), MAX_WAIT)
            return await dg.runs.wait(accepted.run_id, timeout=limit)

        return await call(started)

    @tool(READS)
    async def list_runs(
        pipeline: str | None = None,
        status: RunStatus | None = None,
        since: str | None = None,
        after: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> Any:
        """List runs, newest first, narrowed to a pipeline, a status, or how far back (`since`, such as `24h`)."""
        return await call(
            lambda dg: dg.runs.list(pipeline=pipeline, status=status, since=since, after=after, limit=limit)
        )

    @tool(READS)
    async def run_stats(since: str = "7d", pipeline: str | None = None, tags: list[str] | None = None) -> Any:
        """Summarise the runs that settled within `since` (such as `7d`), narrowed to a pipeline or to every tag given.

        Answers the runs per day by status, each pipeline's p50, p95 and max duration, and the
        errors and steps that failed most.
        """
        return await call(lambda dg: dg.runs.stats(since=since, pipeline=pipeline, tags=tags or ()))

    @tool(READS)
    async def get_run(run_id: str) -> Any:
        """Read one run: its status, every step's state, and its error when it failed."""
        return await call(lambda dg: dg.runs.get(run_id))

    @tool(READS)
    async def run_attempts(
        run_id: str, step: str | None = None, after: str | None = None, limit: int = DEFAULT_LIMIT
    ) -> Any:
        """List a run's attempts, one per try of a step, with each one's output, error and timing."""
        return await call(lambda dg: dg.runs.attempts(run_id, step=step, after=after, limit=limit))

    @tool(READS)
    async def run_logs(
        run_id: str, step: str | None = None, after: str | None = None, limit: int = DEFAULT_LIMIT
    ) -> Any:
        """Read a run's log lines in order, optionally one step's; pass `next` as `after` for more."""
        return await call(lambda dg: dg.runs.logs(run_id, step=step, after=after, limit=limit))

    @tool(STOPS)
    async def cancel_run(run_id: str) -> Any:
        """Cancel a run: what has not started never does, and running remote work is told to stop."""
        return await call(lambda dg: dg.runs.cancel(run_id))

    @tool(WRITES)
    async def rerun_run(run_id: str, current: bool = False) -> Any:
        """Run a settled run again with its parameters, and for a run entered at a source its input, which replays it.

        The new run pins the version the original ran, or with `current` the pipeline's current one.
        """
        return await call(lambda dg: dg.runs.rerun(run_id, current=current))

    @tool(WRITES)
    async def pause_run(run_id: str) -> Any:
        """Pause a queued or running run: nothing more of it starts, and its deadlines stand still."""
        return await call(lambda dg: dg.runs.pause(run_id))

    @tool(WRITES)
    async def resume_run(run_id: str) -> Any:
        """Resume a paused run, its open deadlines moved on by as long as it was paused."""
        return await call(lambda dg: dg.runs.resume(run_id))

    @tool(WRITES)
    async def retry_attempt(attempt_id: str) -> Any:
        """Retry one failed, skipped or cancelled attempt of a run, which reopens the run."""
        return await call(lambda dg: dg.runs.retry(attempt_id))

    @tool(READS)
    async def list_blocks(kind: BlockKind | None = None) -> Any:
        """List the installed blocks a step can use, each with its id, kind and one-line summary."""

        async def listed(dg: Dirigent) -> Any:
            catalog = await dg.blocks.catalog(kind=kind)
            return {
                "blocks": [
                    {"id": entry.id, "kind": entry.kind, "group": entry.group, "summary": entry.summary}
                    for entry in catalog.blocks
                ]
            }

        return await call(listed)

    @tool(READS)
    async def get_block(block_id: str) -> Any:
        """Read one block: the schema a step's `config` is checked against, and the schema of its output."""
        return await call(lambda dg: dg.blocks.get(block_id))

    @tool(READS)
    async def list_examples(
        shelf: str | None = None, tags: list[str] | None = None, after: str | None = None, limit: int = DEFAULT_LIMIT
    ) -> Any:
        """List the example documents the instance ships, optionally one shelf's or those with every tag given."""
        return await call(lambda dg: dg.examples.list(shelf=shelf, tags=tags or (), after=after, limit=limit))

    @tool(READS)
    async def get_example(code: str) -> Any:
        """Read one example, its document included, which is a working starting point for a new one."""
        return await call(lambda dg: dg.examples.get(code))

    @tool(READS)
    async def list_sources(pipeline: str | None = None, after: str | None = None, limit: int = DEFAULT_LIMIT) -> Any:
        """List the input sources, every pipeline's or one's, with each one's state and what it listens to."""
        return await call(lambda dg: dg.sources.list(pipeline, after=after, limit=limit))

    @tool(READS)
    async def source_inputs(pipeline: str, code: str, after: str | None = None, limit: int = DEFAULT_LIMIT) -> Any:
        """List what arrived at one source, newest first, each with its outcome and the run it started."""
        return await call(lambda dg: dg.sources.inputs(pipeline, code, after=after, limit=limit))

    @tool(WRITES)
    async def pause_source(pipeline: str, code: str) -> Any:
        """Pause a source: it takes no new input, and what is in flight finishes."""
        return await call(lambda dg: dg.sources.pause(pipeline, code))

    @tool(WRITES)
    async def resume_source(pipeline: str, code: str) -> Any:
        """Resume a paused source."""
        return await call(lambda dg: dg.sources.resume(pipeline, code))

    @tool(READS)
    async def list_schedules(pipeline: str, after: str | None = None, limit: int = DEFAULT_LIMIT) -> Any:
        """List a pipeline's schedules, each with its clock and when it next fires."""
        return await call(lambda dg: dg.schedules.list(pipeline, after=after, limit=limit))

    @tool(WRITES)
    async def pause_schedule(pipeline: str, code: str) -> Any:
        """Pause a schedule, so it fires no more until it is resumed."""
        return await call(lambda dg: dg.schedules.pause(pipeline, code))

    @tool(WRITES)
    async def resume_schedule(pipeline: str, code: str) -> Any:
        """Resume a paused schedule from its next firing."""
        return await call(lambda dg: dg.schedules.resume(pipeline, code))

    return server


def _json(value: Any) -> Any:
    """Turn what the client answered into one JSON document, a model in its wire shape."""
    return ANSWER.dump_python(value, mode="json", exclude_none=True)


def arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Read the command line: which transport, and for HTTP where to listen."""
    parser = argparse.ArgumentParser(prog="dirigent-mcp", description="Operate a dirigent instance over MCP.")
    parser.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    parser.add_argument("--host", default=DEFAULT_HOST, help="the address HTTP listens on, loopback by default")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="the port HTTP listens on")
    parser.add_argument("--allow-remote", action="store_true", help="listen on an address other machines can reach")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    """Serve over stdio with the environment's token, or over HTTP with each caller's own."""
    given = arguments(argv)
    url = os.environ.get(URL_ENV)
    read_only = os.environ.get(READ_ONLY_ENV, "").strip().lower() in {"1", "true", "yes"}
    if given.transport == "stdio":
        if not url:
            sys.stderr.write(f"dirigent-mcp: {NO_INSTANCE.render(url_env=URL_ENV, token_env=TOKEN_ENV)}\n")
            raise SystemExit(2)
        token = os.environ.get(TOKEN_ENV)
        build(shared(lambda: Dirigent(url=url, token=token)), read_only=read_only).run("stdio")
        return
    if not url:
        sys.stderr.write(f"dirigent-mcp: {NO_HTTP_INSTANCE.render(url_env=URL_ENV)}\n")
        raise SystemExit(2)
    loopback = is_loopback_host(given.host)
    if not loopback and not given.allow_remote:
        sys.stderr.write(f"dirigent-mcp: {REMOTE_BIND_REFUSED.render(host=given.host)}\n")
        raise SystemExit(2)
    if not loopback:
        sys.stderr.write(f"dirigent-mcp: {REMOTE_BIND.render(host=given.host)}\n")
    import uvicorn

    from dirigent_mcp.standalone import standalone_app

    app = standalone_app(url, loopback=loopback, read_only=read_only)
    uvicorn.run(app, host=given.host, port=given.port, log_level="warning")
