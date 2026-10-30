"""The MCP server: one dirigent instance, operated by an agent through the instance's own API.

Every tool is a call the Python client already makes, so what an agent may do is bounded by
the role of the token it was given, and nothing here deletes. Applying and running a document
is still the whole of the instance's reach: a pipeline the agent writes runs with every
connection the instance holds. Read-only, the server offers the reading tools alone.
"""

import os
import sys
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any, Final

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import TypeAdapter

from dirigent_client import BlockKind, Dirigent, DirigentError, RunStatus
from dirigent_common import JsonMap

#: Where the server finds its instance and its token, the names `dg` reads them from.
URL_ENV: Final = "DG_URL"
TOKEN_ENV: Final = "DG_TOKEN"

#: Set to a true value, the server offers only the tools that read.
READ_ONLY_ENV: Final = "DG_MCP_READ_ONLY"

#: How many rows a listing answers with when the agent names no limit.
DEFAULT_LIMIT: Final = 50

#: The longest a run started with ``wait`` is waited on before its id is answered instead.
MAX_WAIT: Final = timedelta(minutes=10)

READS: Final = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITES: Final = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False)
ANSWER: Final = TypeAdapter[Any](Any)

STOPS: Final = ToolAnnotations(read_only_hint=False, destructive_hint=True, open_world_hint=False)

INSTRUCTIONS: Final = """\
This server operates one dirigent instance: a data pipeline orchestrator whose pipelines are
YAML documents of steps, each step a block with a config. Before writing a document, read
the blocks it will use (list_blocks, get_block) and an example close to it (list_examples,
get_example); plan_document checks a document against the instance without storing it.
A run is started with run_pipeline, read with get_run, run_logs and run_attempts, and run again with rerun_run."""


class Clients:
    """The client the tools share, opened on the first call so it lives on the server's loop."""

    def __init__(self, open_client: Callable[[], Dirigent]) -> None:
        """Hold how to open the client, not the client itself."""
        self._open = open_client
        self._client: Dirigent | None = None

    def get(self) -> Dirigent:
        """The client, opened now if no call has opened it yet."""
        if self._client is None:
            self._client = self._open()
        return self._client


def build(open_client: Callable[[], Dirigent], *, read_only: bool = False) -> MCPServer:
    """Build the server whose tools call the instance ``open_client`` connects to, or only its reading ones."""
    server = MCPServer(name="dirigent", instructions=INSTRUCTIONS, log_level="WARNING")
    clients = Clients(open_client)

    def tool[F: Callable[..., Any]](annotations: ToolAnnotations) -> Callable[[F], F]:
        """Register a tool, unless the server reads only and this tool writes."""
        if read_only and annotations is not READS:
            return lambda function: function
        return server.tool(annotations=annotations)

    async def call[T](work: Callable[[Dirigent], Awaitable[T]]) -> Any:
        """Make one call, answering with its JSON, and a refusal as a tool error the agent reads."""
        try:
            answer = await work(clients.get())
        except DirigentError as error:
            raise ToolError(str(error)) from error
        return _json(answer)

    @tool(READS)
    async def instance_info() -> Any:
        """Describe the instance: its version, database, and how many blocks it has installed."""
        return await call(lambda dg: dg.system.info())

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
        """Report what a stored pipeline would fail on if it ran now, such as a connection gone missing."""

        async def checked(dg: Dirigent) -> Any:
            return {"issues": await dg.pipelines.validate(code)}

        return await call(checked)

    @tool(READS)
    async def plan_document(document: str) -> Any:
        """Check a YAML pipeline or triggers document against the instance without storing it.

        Answers what applying it would do, or every issue that refuses it.
        """
        return await call(lambda dg: dg.pipelines.apply(document, dry_run=True))

    @tool(WRITES)
    async def apply_document(document: str, pause_schedules: bool = False) -> Any:
        """Store a YAML pipeline or triggers document as a new version; an unchanged one is left as it is."""
        return await call(lambda dg: dg.pipelines.apply(document, pause_schedules=pause_schedules))

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


def main() -> None:
    """Serve over stdio, against the instance and with the token the environment names."""
    url = os.environ.get(URL_ENV)
    if not url:
        sys.stderr.write(f"dirigent-mcp: set {URL_ENV} to the instance, and {TOKEN_ENV} to an API token for it\n")
        raise SystemExit(2)
    token = os.environ.get(TOKEN_ENV)
    read_only = os.environ.get(READ_ONLY_ENV, "").strip().lower() in {"1", "true", "yes"}
    build(lambda: Dirigent(url=url, token=token), read_only=read_only).run("stdio")
