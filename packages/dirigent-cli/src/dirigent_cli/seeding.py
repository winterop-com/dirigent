"""Filling a live instance from directories of documents, which ``dg dev --seed`` does at boot.

The seeding goes through the API, so every apply meets the same preflight a person's apply
meets, and a refusal is a record rather than a failure: a corpus is expected to hold
documents an instance will not store. A corpus goes in as connection files, then the
standalone JSON Schemas beside its documents, then the documents; a document refused for
naming something a later one supplies is applied again once the rest are in.
"""

from collections.abc import AsyncIterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from dirigent_cli.local import ConnectionSpec
from dirigent_client import Dirigent, DirigentError, PlanAction, ProvenanceSource, declared_label
from dirigent_common import JsonMap
from dirigent_core.documents import CARRIED, SUFFIXES, is_document, readable
from dirigent_core.protocol import Record, make
from dirigent_core.schemas import code_from_id

__all__ = ["CARRIED", "SUFFIXES", "is_document", "readable", "seed_directories", "seed_installed", "specs"]


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
    files = [(str(path), raw) for directory in directories for path, raw in readable(directory)]
    tally = _Tally()
    async for record in _seed(client, files):
        yield tally.count(record)
    yield make(
        "seed.done",
        at=datetime.now(UTC),
        message="seeded",
        directories=[str(one) for one in directories],
        **tally.counts(),
    )


class _Tally:
    """What a seeding did, read off the records it emitted, so a reader and the summary agree."""

    def __init__(self) -> None:
        """Start from nothing seeded."""
        self.pipelines = 0
        self.refused = 0
        self.connections: set[str] = set()
        self.schemas: set[str] = set()

    def count(self, record: Record) -> Record:
        """Count one record, and hand it back to be emitted."""
        match record["kind"]:
            case "seed.applied":
                self.pipelines += 1
            case "seed.refused":
                self.refused += 1
            case "seed.connection":
                self.connections.add(str(record["connection"]))
            case "seed.schema":
                self.schemas.add(str(record["schema"]))
            case _:
                pass
        return record

    def counts(self) -> dict[str, Any]:
        """The closing record's fields."""
        return {
            "pipelines": self.pipelines,
            "refused": self.refused,
            "connections": sorted(self.connections),
            "schemas": sorted(self.schemas),
        }


async def _seed(client: Dirigent, files: Sequence[tuple[str, JsonMap]]) -> AsyncIterator[Record]:
    """Seed a corpus: its connection files, its standalone schemas, then its documents.

    The connections and the schemas go in before any document, so a document that names one
    passes the preflight that reads it. A document refused in one pass is applied again in
    the next, since what it names may be a pipeline or a schema a later document supplied, and
    the passes end when one stores nothing new; what is still refused is reported then.
    """
    for origin, raw in files:
        if not is_document(raw):
            async for record in _connections(client, specs(raw.get("connections")), origin):
                yield record
    for origin, raw in files:
        code = _schema_file(raw, origin)
        if code is not None:
            yield await _standalone_schema(client, code, raw, origin)
    waiting: list[tuple[str, JsonMap, Record]] = []
    for origin, raw in files:
        if is_document(raw):
            async for record in _carried(client, raw, origin):
                yield record
            applied = await _apply(client, raw, origin)
            if applied["kind"] == "seed.applied":
                yield applied
            else:
                waiting.append((origin, raw, applied))
    while waiting:
        still: list[tuple[str, JsonMap, Record]] = []
        for origin, raw, _refusal in waiting:
            record = await _apply(client, raw, origin)
            if record["kind"] == "seed.applied":
                yield record
            else:
                still.append((origin, raw, record))
        if len(still) == len(waiting):
            break
        waiting = still
    for _origin, _raw, refusal in waiting:
        yield refusal


def _schema_file(raw: JsonMap, origin: str) -> str | None:
    """Name the code a standalone JSON Schema file is stored under, or None when the file is not one.

    A file that is neither a document nor a connection file and declares a string ``$id`` is a
    schema, coded the way ``dg schema create`` codes it: from the ``$id``, else the filename.
    """
    if is_document(raw) or "connections" in raw or not isinstance(raw.get("$id"), str):
        return None
    return code_from_id(cast("str", raw["$id"])) or code_from_id(Path(origin.rpartition(":")[2]).name)


async def _standalone_schema(client: Dirigent, code: str, body: JsonMap, origin: str) -> Record:
    """Store one schema file, and say so, or say why the instance would not."""
    try:
        await _schema(client, code, body)
    except DirigentError as error:
        return _refused(origin, f"schema {code}: {_reason(error)}")
    return make("seed.schema", at=datetime.now(UTC), message="schema", schema=code, origin=origin)


async def _carried(client: Dirigent, raw: JsonMap, origin: str) -> AsyncIterator[Record]:
    """Create the connections and the schemas one document carries."""
    async for record in _connections(client, specs(raw.get("connections")), origin):
        yield record
    for code, body in _schemas(raw).items():
        try:
            await _schema(client, code, body)
        except DirigentError as error:
            yield _refused(origin, f"schema {code}: {_reason(error)}")


def _schemas(raw: JsonMap) -> dict[str, JsonMap]:
    """Read a document's ``schemas:`` section as one body per code."""
    declared = raw.get("schemas")
    if not isinstance(declared, Mapping):
        return {}
    read = cast("Mapping[str, object]", declared)
    return {code: cast("JsonMap", body) for code, body in sorted(read.items()) if isinstance(body, Mapping)}


async def _schema(client: Dirigent, code: str, body: JsonMap) -> None:
    """Store one named schema, replacing the shape and the labels of one already held.

    Storing reads the schema's own ``title`` and ``description`` and editing reads neither, so
    the replacement sends what the document's schema declares about itself; otherwise the same
    corpus would label a schema one way on a fresh instance and another way on a seeded one.
    """
    try:
        await client.schemas.create(body, code=code)
    except DirigentError:
        await client.schemas.update(
            code,
            body=body,
            name=declared_label(body, "title"),
            description=declared_label(body, "description"),
        )


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
        await client.connections.create(
            spec.code, kind=spec.kind, config=spec.config, name=spec.name, description=spec.description
        )
    except DirigentError:
        await client.connections.update(spec.code, config=spec.config)
        return "updated"
    return "created"


async def _apply(client: Dirigent, raw: JsonMap, origin: str) -> Record:
    """Apply one document with its schedules and polled or held sources paused, without the sections it carries."""
    document = {name: value for name, value in raw.items() if name not in CARRIED}
    try:
        result = await client.pipelines.apply(
            document,
            source=ProvenanceSource.FILE,
            source_ref=origin,
            paused=True,
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
        sources_paused=result.sources.paused,
    )


def _refused(origin: str, reason: str) -> Record:
    """Build the record saying what the instance would not take, and why."""
    return make("seed.refused", at=datetime.now(UTC), message="refused", document=origin, reason=reason)


def _reason(error: DirigentError) -> str:
    """Read a refusal as the one line a record carries."""
    return "; ".join(str(problem) for problem in error.problems) or error.message


async def seed_installed(client: Dirigent) -> AsyncIterator[Record]:
    """Seed every installed corpus the way a directory is seeded, files beside the documents included.

    The corpus is what this build ships, so nothing is named on the command line and no
    checkout has to be present. A file is attributed to the plugin that carries it.
    """
    from dirigent_core.plugins import load_plugin_host

    shipped = load_plugin_host().example_files()
    files = [(f"{one.plugin}:{one.path}", one.raw) for one in shipped]
    tally = _Tally()
    async for record in _seed(client, files):
        yield tally.count(record)
    yield make(
        "seed.done",
        at=datetime.now(UTC),
        message="seeded",
        plugins=sorted({one.plugin for one in shipped if is_document(one.raw)}),
        **tally.counts(),
    )
