"""The source command group: where a pipeline's inputs enter, what has arrived, and calling one."""

import json
from pathlib import Path
from typing import Annotated, Final

import httpx2
import typer
from pydantic import JsonValue

from dirigent_cli.commands import fail, paged
from dirigent_cli.context import client_for, state_of
from dirigent_cli.messages import ONE_INPUT_BODY, SOURCE_NOT_CALLABLE, SOURCE_UNREACHABLE, TAKES_NAME_EQUALS_VALUE
from dirigent_cli.output import emit_fact, emit_one, emit_records
from dirigent_client import DEFAULT_CONNECT_TIMEOUT
from dirigent_plugin.sources import Route

#: Where ``dg source call`` reads the token a source was given when ``--source-token`` names none.
TOKEN_ENV: Final = "DIRIGENT_SOURCE_TOKEN"

#: How long a call waits for its answer, past the longest an instance holds a caller by default.
CALL_TIMEOUT: Final = httpx2.Timeout(90.0, connect=DEFAULT_CONNECT_TIMEOUT)

source_app = typer.Typer(
    name="source",
    help="Where a pipeline's inputs enter: what each listens to, what has arrived, and calling one.",
    no_args_is_help=True,
)

PipelineArg = Annotated[str, typer.Argument(help="The pipeline the source belongs to.")]
SourceArg = Annotated[str, typer.Argument(help="The source's step code.")]


@source_app.command("list")
def source_list(
    ctx: typer.Context,
    pipeline: Annotated[
        str | None, typer.Argument(help="The pipeline whose sources to list; every one when unset.")
    ] = None,
) -> None:
    """List sources with their state and what they have taken, never their tokens."""
    with client_for(state_of(ctx)) as dg:
        rows = list(paged(lambda after, size: dg.call(dg.sources.list(pipeline, after=after, limit=size)), None))
    emit_records("source", rows)


@source_app.command("show")
def source_show(ctx: typer.Context, pipeline: PipelineArg, code: SourceArg) -> None:
    """Show one source: its route, its state, and what it has taken."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.sources.get(pipeline, code))
    emit_one("source", row)


@source_app.command("pause")
def source_pause(ctx: typer.Context, pipeline: PipelineArg, code: SourceArg) -> None:
    """Refuse new inputs with 503, keeping the token and the counts; runs in flight carry on."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.sources.pause(pipeline, code))
    emit_fact("source.paused", message="paused", code=code, pipeline=pipeline, state=row.state.value)


@source_app.command("resume")
def source_resume(ctx: typer.Context, pipeline: PipelineArg, code: SourceArg) -> None:
    """Take inputs again on the token that was already issued."""
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.sources.resume(pipeline, code))
    emit_fact("source.resumed", message="resumed", code=code, pipeline=pipeline, state=row.state.value)


@source_app.command("rotate-token")
def source_rotate(ctx: typer.Context, pipeline: PipelineArg, code: SourceArg) -> None:
    """Mint a new token and forget the old one; every caller has to be given the new one."""
    with client_for(state_of(ctx)) as dg:
        minted = dg.call(dg.sources.rotate_token(pipeline, code))
        base = dg.url
    emit_fact(
        "source.token_rotated",
        message="rotated",
        code=code,
        pipeline=pipeline,
        url=f"{base.rstrip('/')}{minted.url_path}",
        token=minted.token,
    )


@source_app.command("inputs")
def source_inputs(
    ctx: typer.Context,
    pipeline: PipelineArg,
    code: SourceArg,
    limit: Annotated[int, typer.Option(help="How many inputs to show, newest first.")] = 50,
) -> None:
    """List what has arrived at a source, newest first, refusals included."""
    with client_for(state_of(ctx)) as dg:
        rows = list(
            paged(lambda after, size: dg.call(dg.sources.inputs(pipeline, code, after=after, limit=size)), limit)
        )
    emit_records("source.input", rows)


@source_app.command("call")
def source_call(
    ctx: typer.Context,
    pipeline: PipelineArg,
    code: SourceArg,
    data: Annotated[str | None, typer.Option("--body", help="A JSON body, or @file to read one from a file.")] = None,
    text: Annotated[str | None, typer.Option("--text", help="A text body, or @file to read one from a file.")] = None,
    form: Annotated[
        list[str] | None, typer.Option("--form", help="One name=value of a urlencoded form body; repeat for more.")
    ] = None,
    method: Annotated[
        str | None, typer.Option("--method", "-X", help="The method to call with; the source's first unless set.")
    ] = None,
    path_params: Annotated[
        list[str] | None, typer.Option("--path-param", "-p", help="One name=value the path template takes.")
    ] = None,
    query: Annotated[list[str] | None, typer.Option("--query", "-q", help="One name=value of the query.")] = None,
    token: Annotated[
        str | None,
        typer.Option("--source-token", envvar=TOKEN_ENV, help="The source's own token, not the CLI's credential."),
    ] = None,
) -> None:
    """Call a received source the way its callers do, and write down what it answered.

    The call carries the source's own token, never this CLI's: an endpoint authenticates its
    caller as the source, not as a person.
    """
    if sum(value is not None for value in (data, text, form)) > 1:
        fail(ONE_INPUT_BODY)
    with client_for(state_of(ctx)) as dg:
        row = dg.call(dg.sources.get(pipeline, code))
        base = dg.url
    if row.url_path is None or not row.methods:
        fail(SOURCE_NOT_CALLABLE, code=repr(code), pipeline=repr(pipeline), kind=repr(row.kind))
    chosen = (method or row.methods[0]).upper()
    url = base.rstrip("/") + Route(methods=tuple(row.methods), template=row.url_path).fill(_pairs(path_params))
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    content: bytes | None = None
    if data is not None:
        content = _read(data).encode()
        headers["Content-Type"] = "application/json"
    elif text is not None:
        content = _read(text).encode()
        headers["Content-Type"] = "text/plain; charset=utf-8"
    try:
        with httpx2.Client(timeout=CALL_TIMEOUT) as http:
            answered = http.request(
                chosen,
                url,
                headers=headers,
                params=_pairs(query),
                content=content,
                data=_pairs(form) if form is not None else None,
            )
    except httpx2.HTTPError as error:
        fail(SOURCE_UNREACHABLE, url=url, detail=str(error))
    emit_fact(
        "source.called",
        message=f"answered {answered.status_code}",
        code=code,
        pipeline=pipeline,
        method=chosen,
        url=url,
        status=answered.status_code,
        body=_body_of(answered),
    )
    if answered.status_code >= 400:
        raise typer.Exit(code=1)


def _read(value: str) -> str:
    """Read a value, or the file an ``@`` before it names."""
    if value.startswith("@"):
        return Path(value[1:]).expanduser().read_text()
    return value


def _pairs(entries: list[str] | None) -> dict[str, str]:
    """Read repeated ``name=value`` options into a mapping."""
    pairs: dict[str, str] = {}
    for entry in entries or ():
        name, equals, value = entry.partition("=")
        if not equals or not name:
            fail(TAKES_NAME_EQUALS_VALUE, entry=repr(entry))
        pairs[name] = value
    return pairs


def _body_of(answered: httpx2.Response) -> JsonValue:
    """Read what an endpoint answered with: JSON when it says so, its text otherwise, nothing when empty."""
    if not answered.content:
        return None
    if "json" in answered.headers.get("content-type", ""):
        try:
            parsed: JsonValue = json.loads(answered.content)
        except ValueError:
            return answered.text
        return parsed
    return answered.text


__all__ = ["TOKEN_ENV", "source_app"]
