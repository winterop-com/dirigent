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
import json
import os
import sys
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from datetime import timedelta
from enum import IntEnum
from typing import Any, Final, cast

from mcp.server import MCPServer
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver.exceptions import ResourceError, ToolError
from mcp.types import ToolAnnotations
from pydantic import TypeAdapter
from starlette.requests import Request

from dirigent_client import BlockEntry, BlockKind, Dirigent, DirigentError, RunStatus
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

#: Reads the instance and changes nothing.
READS: Final = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)

#: Sets a state the instance holds; asking twice leaves it as asking once did.
TOGGLES: Final = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)

#: Changes how a run in flight proceeds; asking twice is refused or does more.
STEERS: Final = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False
)

#: Starts work, which runs every step of a pipeline against whatever its blocks reach.
STARTS: Final = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=True
)

#: Stores a document, retiring what it stops declaring; the same document twice changes nothing more.
APPLIES: Final = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False
)

#: Ends work that cannot be resumed.
STOPS: Final = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
)

#: Replaces a credential, so every caller holding the old one is shut out.
ROTATES: Final = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False
)

#: Asks an outside system whether it answers, and records what it said.
PROBES: Final = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
)

ANSWER: Final = TypeAdapter[Any](Any)

INSTRUCTIONS: Final = """\
This server operates one dirigent instance: a data pipeline orchestrator whose pipelines are
YAML documents of steps, each step a block with a config. Before writing a document, read
the blocks it will use (list_blocks, get_block) and an example close to it (list_examples,
get_example); plan_document checks a document against the instance without storing it, and
lists under sources.removed and triggers.schedules_removed what applying it would retire.
apply_document retires a source, with its input journal and token, and a schedule when the
document stops declaring them, so plan first and keep every source and schedule a pipeline has.
A run is started with run_pipeline, read with get_run, run_logs and run_attempts, and run again with rerun_run.
The resources dirigent://schema/document and dirigent://blocks are the document format and the
block catalogue to write against."""


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


class Offers(IntEnum):
    """Which tools a server offers: those the API allows to a role, each including the one before."""

    READING = 0
    OPERATING = 1
    ADMINISTERING = 2


def build(connect: Connect, *, offers: Offers = Offers.ADMINISTERING) -> MCPServer:
    """Build the server whose tools call the instance through ``connect``, the ones ``offers`` reaches."""
    server = MCPServer(name="dirigent", instructions=INSTRUCTIONS, log_level="WARNING", middleware=[remember_request])

    def tool[F: Callable[..., Any]](annotations: ToolAnnotations, needs: Offers | None = None) -> Callable[[F], F]:
        """Register a tool the server offers: ``needs`` says who, or else whether the tool writes."""
        least = needs if needs is not None else Offers.READING if annotations.read_only_hint else Offers.OPERATING
        if least > offers:
            return lambda function: function
        return server.tool(annotations=annotations)

    async def read_resource[T](work: Callable[[Dirigent], Awaitable[T]]) -> T:
        """Read what a resource serves, a refusal as a resource error the agent reads."""
        try:
            async with connect() as dg:
                return await work(dg)
        except DirigentError as error:
            raise ResourceError(str(error)) from error

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

    @tool(READS, needs=Offers.OPERATING)
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

    @tool(STARTS)
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
        """Read one run: its status, every step's state, and its error when it failed.

        `via` says how the input of a run entered at a source arrived: `request` (a caller, whom a
        reply answers), `poll`, `hold`, `hand` (given by hand, or replayed by a rerun) or `sample`
        (by hand with the source's own sample); null for a run with no source. `stored_bytes` is
        what the run's steps have written to artifact storage.
        """

        async def read(dg: Dirigent) -> Any:
            detail = await dg.runs.get(run_id)
            via = None
            if detail.run.source is not None:
                entered = await dg.runs.attempts(run_id, step=detail.run.source, limit=1)
                via = next((attempt.via for attempt in entered.items if attempt.via is not None), None)
            return {**_json(detail), "via": via, "stored_bytes": detail.run.stored_bytes}

        return await call(read)

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

    @tool(STARTS)
    async def rerun_run(run_id: str, current: bool = False) -> Any:
        """Run a settled run again with its parameters, and for a run entered at a source its input, which replays it.

        The new run pins the version the original ran, or with `current` the pipeline's current one.
        """
        return await call(lambda dg: dg.runs.rerun(run_id, current=current))

    @tool(STEERS)
    async def pause_run(run_id: str) -> Any:
        """Pause a queued or running run: nothing more of it starts, and its deadlines stand still."""
        return await call(lambda dg: dg.runs.pause(run_id))

    @tool(STEERS)
    async def resume_run(run_id: str) -> Any:
        """Resume a paused run, its open deadlines moved on by as long as it was paused."""
        return await call(lambda dg: dg.runs.resume(run_id))

    @tool(STARTS)
    async def retry_attempt(attempt_id: str) -> Any:
        """Retry one failed, skipped or cancelled attempt of a run, which reopens the run."""
        return await call(lambda dg: dg.runs.retry(attempt_id))

    @tool(READS)
    async def list_blocks(kind: BlockKind | None = None) -> Any:
        """List the installed blocks a step can use, each with its id, kind and one-line summary."""

        async def listed(dg: Dirigent) -> Any:
            catalog = await dg.blocks.catalog(kind=kind)
            return {"blocks": [_summary(entry) for entry in catalog.blocks]}

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

    @tool(TOGGLES)
    async def pause_source(pipeline: str, code: str) -> Any:
        """Pause a source: it takes no new input, and what is in flight finishes."""
        return await call(lambda dg: dg.sources.pause(pipeline, code))

    @tool(TOGGLES)
    async def resume_source(pipeline: str, code: str) -> Any:
        """Resume a paused source."""
        return await call(lambda dg: dg.sources.resume(pipeline, code))

    @tool(READS)
    async def get_source(pipeline: str, code: str) -> Any:
        """Read one source: its state, what it has taken, and for an endpoint where and how it is called.

        `calling.url` is the full URL a caller sends to, with `calling.methods`. `calling.auth` is
        `token` (a bearer token whose leading characters are `token_prefix`), `hmac` (a signature of
        the body in `signature_header`, with the secret's `secret_fingerprint`) or `public`. Neither
        the token nor the secret is ever shown here; rotate_source_token mints a new one.
        """

        async def read(dg: Dirigent) -> Any:
            source = await dg.sources.get(pipeline, code)
            answered = _json(source)
            if source.url_path is not None:
                answered["calling"] = {
                    "url": f"{dg.url.rstrip('/')}{source.url_path}",
                    "methods": source.methods,
                    "auth": source.auth,
                    "token_prefix": source.token_prefix,
                    "signature_header": source.signature_header,
                    "secret_fingerprint": source.secret_fingerprint,
                }
            return answered

        return await call(read)

    @tool(ROTATES)
    async def rotate_source_token(pipeline: str, code: str) -> Any:
        """Mint a new token, or signing secret, for an endpoint source, and forget the old one at once.

        Every caller holding the old one is refused from now on. The answer carries the new one, and
        it is shown here and nowhere else again.
        """
        return await call(lambda dg: dg.sources.rotate_token(pipeline, code))

    @tool(READS)
    async def list_connections(after: str | None = None, limit: int = DEFAULT_LIMIT) -> Any:
        """List the connections a document can name, each with its kind and settings; secrets are never shown."""
        return await call(lambda dg: dg.connections.list(after=after, limit=limit))

    @tool(READS)
    async def get_connection(code: str) -> Any:
        """Read one connection: its kind, its settings with every secret redacted, and its last health check."""
        return await call(lambda dg: dg.connections.get(code))

    @tool(PROBES, needs=Offers.ADMINISTERING)
    async def check_connection(code: str) -> Any:
        """Ask a connection's outside system whether it answers with the stored credential, and record it."""
        return await call(lambda dg: dg.connections.check(code))

    @tool(READS)
    async def list_schemas(after: str | None = None, limit: int = DEFAULT_LIMIT) -> Any:
        """List the named JSON Schemas a document can reference."""
        return await call(lambda dg: dg.schemas.list(after=after, limit=limit))

    @tool(READS)
    async def get_schema(code: str) -> Any:
        """Read one named JSON Schema, the schema itself included."""
        return await call(lambda dg: dg.schemas.get(code))

    @tool(READS)
    async def list_alert_rules(after: str | None = None, limit: int = DEFAULT_LIMIT) -> Any:
        """List the alert rules: what event each listens for, where it sends, and whether it is paused."""
        return await call(lambda dg: dg.alerts.rules(after=after, limit=limit))

    @tool(READS)
    async def get_alert_rule(code: str) -> Any:
        """Read one alert rule."""
        return await call(lambda dg: dg.alerts.rule(code))

    @server.resource(
        "dirigent://schema/document",
        name="document-schema",
        title="Document format",
        description=(
            "The JSON Schema a pipeline or triggers document is written against, "
            "every installed block's config included."
        ),
        mime_type="application/schema+json",
    )
    async def document_schema() -> str:
        return json.dumps(await read_resource(lambda dg: dg.blocks.document_schema()))

    @server.resource(
        "dirigent://blocks",
        name="blocks",
        title="Block catalogue",
        description="Every installed block a step can use, with its id, kind, group and one-line summary.",
        mime_type="application/json",
    )
    async def blocks() -> str:
        catalog = await read_resource(lambda dg: dg.blocks.catalog())
        return json.dumps({"blocks": [_summary(entry) for entry in catalog.blocks]})

    @server.resource(
        "dirigent://blocks/{block_id}",
        name="block",
        title="Block",
        description="One block: the schema a step's config is checked against, and the schema of its output.",
        mime_type="application/json",
    )
    async def block(block_id: str) -> str:
        return json.dumps(_json(await read_resource(lambda dg: dg.blocks.get(block_id))))

    @tool(READS)
    async def list_schedules(pipeline: str, after: str | None = None, limit: int = DEFAULT_LIMIT) -> Any:
        """List a pipeline's schedules, each with its clock and when it next fires."""
        return await call(lambda dg: dg.schedules.list(pipeline, after=after, limit=limit))

    @tool(TOGGLES)
    async def pause_schedule(pipeline: str, code: str) -> Any:
        """Pause a schedule, so it fires no more until it is resumed."""
        return await call(lambda dg: dg.schedules.pause(pipeline, code))

    @tool(TOGGLES)
    async def resume_schedule(pipeline: str, code: str) -> Any:
        """Resume a paused schedule from its next firing."""
        return await call(lambda dg: dg.schedules.resume(pipeline, code))

    return server


def _summary(entry: BlockEntry) -> JsonMap:
    """One block as a listing shows it."""
    return {"id": entry.id, "kind": entry.kind, "group": entry.group, "summary": entry.summary}


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
        offers = Offers.READING if read_only else Offers.ADMINISTERING
        build(shared(lambda: Dirigent(url=url, token=token)), offers=offers).run("stdio")
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
