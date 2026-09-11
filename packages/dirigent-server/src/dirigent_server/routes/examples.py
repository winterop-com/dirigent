"""The example corpus every installed plugin contributes, and the source of one document.

The catalogue is read off the plugin host rather than the database: it is what this build of
the instance ships, not what anyone applied. The host walks the shelves once, on the first
request that asks for them.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from dirigent_client.schemas import ExampleDetail, ExampleOut, Page
from dirigent_core.examples import ExampleEntry
from dirigent_core.plugins import UnknownExample
from dirigent_server.dependencies import ServicesDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip
from dirigent_server.security import PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["examples"])


def render(entry: ExampleEntry) -> ExampleOut:
    """Render one catalogue entry for a listing."""
    return ExampleOut(
        code=entry.code,
        name=entry.name,
        description=entry.description,
        tags=entry.tags,
        requires=entry.requires,
        plugin=entry.plugin,
        shelf=entry.shelf,
        starter=entry.starter,
        carries=entry.carries,
    )


@router.get("/examples", operation_id="listExamples", summary="List examples", response_model=Page[ExampleOut])
async def list_examples(
    services: ServicesDep,
    principal: PrincipalDep,
    tag: Annotated[
        list[str] | None,
        Query(description="Only documents wearing this tag; repeat it to name more, and all must match."),
    ] = None,
    shelf: Annotated[str | None, Query(description="Only documents on this shelf.")] = None,
    plugin: Annotated[str | None, Query(description="Only documents this distribution ships.")] = None,
    starter: Annotated[
        bool | None, Query(description="Only the documents that may be copied, or only the ones that may not.")
    ] = None,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[ExampleOut]:
    """List the documents every installed plugin ships, in plugin, shelf, code order."""
    wanted = set(tag or [])
    found = [
        render(entry)
        for entry in services.host.examples()
        if wanted <= set(entry.tags)
        and (shelf is None or entry.shelf == shelf)
        and (plugin is None or entry.plugin == plugin)
        and (starter is None or entry.starter is starter)
    ]
    if after is not None:
        found = [entry for entry in found if _cursor(entry) > after]
    items, following = clip(found[: limit + 1], limit, _cursor)
    return Page(items=items, next=following)


def _cursor(entry: ExampleOut) -> str:
    """Name a row the way the listing orders it, so a cursor continues that order."""
    return f"{entry.plugin}/{entry.shelf}/{entry.code}"


@router.get(
    "/examples/{code}",
    operation_id="readExample",
    summary="Read an example",
    response_model=ExampleDetail,
)
async def read_example(code: str, services: ServicesDep, principal: PrincipalDep) -> ExampleDetail:
    """Read one example by its code, with the text a copy of it copies."""
    try:
        entry = services.host.example(code)
    except UnknownExample as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if error.plugins else status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    return ExampleDetail(**render(entry).model_dump(), source=entry.source, path=entry.path)
