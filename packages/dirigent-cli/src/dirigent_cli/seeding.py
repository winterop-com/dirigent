"""Filling a live instance from directories of documents, which ``dg dev --seed`` does at boot.

The seeding goes through the API, so every apply meets the same preflight a person's apply
meets, and a refusal is a record rather than a failure: a corpus is expected to hold
documents an instance will not store.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from dirigent_cli.local import ConnectionSpec
from dirigent_client import Dirigent, DirigentError, PlanAction, ProvenanceSource
from dirigent_common import JsonMap
from dirigent_core.documents import CARRIED, SUFFIXES, is_document, readable
from dirigent_core.protocol import Record, make

__all__ = ["CARRIED", "SUFFIXES", "is_document", "readable", "seed_directories", "specs"]


def specs(declared: object) -> list[ConnectionSpec]:
    """Read a ``connections:`` section, of a file or of a document, into one spec per code."""
    if not isinstance(declared, Mapping):
        return []
    read: list[ConnectionSpec] = []
    for code, body in sorted(cast("Mapping[str, object]", declared).items()):
        fields = cast("dict[str, Any]", body) if isinstance(body, Mapping) else {}
        read.append(ConnectionSpec.model_validate({**fields, "code": code}))
    return read


async def seed_directories(client: Dirigent, directories: Sequence[Path]) -> AsyncIterator[Record]:
    """Apply every document under each directory, paused, and create what they need first.

    The closing record's counts are read off the records the seeding emitted, so a reader of
    the stream and this summary never disagree.
    """
    pipelines = 0
    refused = 0
    connections: set[str] = set()
    async for record in _walk(client, directories):
        kind = record["kind"]
        if kind == "seed.applied":
            pipelines += 1
        elif kind == "seed.refused":
            refused += 1
        elif kind == "seed.connection":
            connections.add(str(record["connection"]))
        yield record
    yield make(
        "seed.done",
        at=datetime.now(UTC),
        message="seeded",
        directories=[str(one) for one in directories],
        pipelines=pipelines,
        refused=refused,
        connections=sorted(connections),
    )


async def _walk(client: Dirigent, directories: Sequence[Path]) -> AsyncIterator[Record]:
    """Seed each directory in the order given: the connections it declares, then its documents.

    A directory's own connection files go in before any of its documents, so a document that
    names one of them passes the preflight that reads it.
    """
    for directory in directories:
        files = readable(directory)
        for path, raw in files:
            if not is_document(raw):
                async for record in _connections(client, specs(raw.get("connections")), str(path)):
                    yield record
        for path, raw in files:
            if is_document(raw):
                async for record in _document(client, raw, str(path)):
                    yield record


async def _document(client: Dirigent, raw: JsonMap, origin: str) -> AsyncIterator[Record]:
    """Create what one document carries, then apply the document without those sections."""
    async for record in _connections(client, specs(raw.get("connections")), origin):
        yield record
    for code, body in _schemas(raw).items():
        try:
            await _schema(client, code, body)
        except DirigentError as error:
            yield _refused(origin, f"schema {code}: {_reason(error)}")
    yield await _apply(client, raw, origin)


def _schemas(raw: JsonMap) -> dict[str, JsonMap]:
    """Read a document's ``schemas:`` section as one body per code."""
    declared = raw.get("schemas")
    if not isinstance(declared, Mapping):
        return {}
    read = cast("Mapping[str, object]", declared)
    return {code: cast("JsonMap", body) for code, body in sorted(read.items()) if isinstance(body, Mapping)}


async def _schema(client: Dirigent, code: str, body: JsonMap) -> None:
    """Store one named schema, replacing the body of one this instance already holds."""
    try:
        await client.schemas.create(body, code=code)
    except DirigentError:
        await client.schemas.update(code, body=body)


async def _connections(client: Dirigent, declared: Sequence[ConnectionSpec], origin: str) -> AsyncIterator[Record]:
    """Create each declared connection, or replace the config of one that is already there."""
    for spec in declared:
        try:
            action = await _connection(client, spec)
        except DirigentError as error:
            yield _refused(origin, f"connection {spec.code}: {_reason(error)}")
            continue
        yield make(
            "seed.connection",
            at=datetime.now(UTC),
            message="connection",
            connection=spec.code,
            connection_kind=spec.kind,
            action=action,
            origin=origin,
        )


async def _connection(client: Dirigent, spec: ConnectionSpec) -> str:
    """Store one connection and say whether it was new, letting a refusal through."""
    try:
        await client.connections.create(spec.code, kind=spec.kind, config=spec.config, name=spec.name)
    except DirigentError:
        await client.connections.update(spec.code, config=spec.config)
        return "updated"
    return "created"


async def _apply(client: Dirigent, raw: JsonMap, origin: str) -> Record:
    """Apply one document with its schedules paused, without the sections it carries."""
    document = {name: value for name, value in raw.items() if name not in CARRIED}
    try:
        result = await client.pipelines.apply(
            document,
            source=ProvenanceSource.FILE,
            source_ref=origin,
            pause_schedules=True,
        )
    except DirigentError as error:
        return _refused(origin, _reason(error))
    if result.plan.action is PlanAction.INVALID:
        return _refused(origin, "; ".join(str(issue) for issue in result.plan.issues))
    return make(
        "seed.applied",
        at=datetime.now(UTC),
        message="applied",
        document=origin,
        pipeline=result.plan.code,
        action=result.plan.action.value,
        schedules_paused=result.triggers.schedules_created,
    )


def _refused(origin: str, reason: str) -> Record:
    """Build the record saying what the instance would not take, and why."""
    return make("seed.refused", at=datetime.now(UTC), message="refused", document=origin, reason=reason)


def _reason(error: DirigentError) -> str:
    """Read a refusal as the one line a record carries."""
    return "; ".join(error.problems) or error.message
