"""Tests for artifact references: inline when small, stored behind a URI when not."""

import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import AttemptStatus
from dirigent_core.artifacts import (
    ObjectMissing,
    canonical_json,
    digest_of,
    load_artifact,
    load_document,
    open_artifact,
    persist_document,
    persist_output,
)
from dirigent_core.database import session_scope
from dirigent_core.ids import uuid7
from dirigent_core.models import ArtifactRef, Pipeline, PipelineVersion, Run, StepAttempt
from dirigent_core.storage import Storage


async def make_attempt(sessions: async_sessionmaker[AsyncSession]) -> StepAttempt:
    """Create the minimum rows an artifact needs to hang off."""
    async with session_scope(sessions) as session:
        pipeline = Pipeline(code="artifacts")
        session.add(pipeline)
        await session.flush()
        version = PipelineVersion(pipeline_id=pipeline.id, version=1, document={}, digest="sha256:x")
        session.add(version)
        await session.flush()
        run = Run(pipeline_id=pipeline.id, pipeline_version_id=version.id)
        session.add(run)
        await session.flush()
        attempt = StepAttempt(
            run_id=run.id, step_name="only", block_id="test.echo", attempt=1, status=AttemptStatus.RUNNING
        )
        session.add(attempt)
        await session.flush()
        return attempt


def test_canonical_json_is_stable_and_hashable() -> None:
    first = canonical_json({"b": 1, "a": [1, 2]})
    second = canonical_json({"a": [1, 2], "b": 1})
    assert first == second == b'{"a":[1,2],"b":1}'
    assert digest_of(first) == digest_of(second)
    assert digest_of(first).startswith("sha256:")


async def test_a_small_output_inlines_into_the_row(sessions: async_sessionmaker[AsyncSession], services: Any) -> None:
    attempt = await make_attempt(sessions)
    async with session_scope(sessions) as session:
        stored = await session.get(StepAttempt, attempt.id)
        assert stored is not None
        reference = await persist_output(session, services.storage, stored, {"value": "small"}, inline_max_bytes=1024)
        artifact_id = reference.id

    async with sessions() as session:
        artifact = await session.get(ArtifactRef, artifact_id)
        assert artifact is not None
        assert artifact.inline_value == {"value": "small"}
        assert artifact.uri is None
        assert artifact.size_bytes == 17
        assert artifact.content_type == "application/json"
        settled = await session.get(StepAttempt, attempt.id)
        assert settled is not None
        assert settled.output == {"value": "small"}
        assert settled.output_artifact_id == artifact_id
        assert await load_artifact(session, services.storage, artifact_id) == {"value": "small"}


async def test_a_large_output_is_stored_behind_a_uri(sessions: async_sessionmaker[AsyncSession], services: Any) -> None:
    attempt = await make_attempt(sessions)
    payload = {"rows": ["x" * 100 for _ in range(50)]}
    async with session_scope(sessions) as session:
        stored = await session.get(StepAttempt, attempt.id)
        assert stored is not None
        reference = await persist_output(session, services.storage, stored, payload, inline_max_bytes=64)
        artifact_id = reference.id
        uri = reference.uri

    assert uri is not None
    assert uri.endswith(f"{attempt.id}.json")
    storage: Storage = services.storage
    assert json.loads(await storage.read_bytes(uri)) == payload

    async with sessions() as session:
        artifact = await session.get(ArtifactRef, artifact_id)
        assert artifact is not None
        assert artifact.inline_value is None
        assert artifact.scheme == "file"
        assert await load_artifact(session, storage, artifact_id) == payload


async def test_reading_an_artifact_that_does_not_exist_returns_nothing(
    sessions: async_sessionmaker[AsyncSession], services: Any
) -> None:
    async with sessions() as session:
        assert await load_artifact(session, services.storage, uuid7()) is None


async def test_an_artifact_with_neither_a_value_nor_a_uri_reads_as_nothing(
    sessions: async_sessionmaker[AsyncSession], services: Any
) -> None:
    attempt = await make_attempt(sessions)
    async with session_scope(sessions) as session:
        empty = ArtifactRef(run_id=attempt.run_id, step_attempt_id=attempt.id, step_name="only")
        session.add(empty)
        await session.flush()
        artifact_id = empty.id
    async with sessions() as session:
        assert await load_artifact(session, services.storage, artifact_id) is None


async def test_an_artifact_whose_object_is_gone_names_what_is_missing(
    sessions: async_sessionmaker[AsyncSession], services: Any
) -> None:
    """A database restored without its artifact root reads as one refusal, not a stack trace."""
    attempt = await make_attempt(sessions)
    payload = {"rows": ["x" * 100 for _ in range(50)]}
    async with session_scope(sessions) as session:
        stored = await session.get(StepAttempt, attempt.id)
        assert stored is not None
        reference = await persist_output(session, services.storage, stored, payload, inline_max_bytes=64)
        artifact_id, uri = reference.id, reference.uri

    assert uri is not None
    await services.storage.delete(uri)

    async with sessions() as session:
        with pytest.raises(ObjectMissing) as raised:
            await load_artifact(session, services.storage, artifact_id)

    assert raised.value.code == "artifacts.object_missing"
    assert raised.value.status == 404
    assert raised.value.params == {"uri": uri, "run": str(attempt.run_id), "attempt": str(attempt.id)}
    assert "restore the artifact root" in str(raised.value)


async def test_a_document_whose_object_is_gone_refuses_for_the_run_itself(
    sessions: async_sessionmaker[AsyncSession], services: Any
) -> None:
    attempt = await make_attempt(sessions)
    async with session_scope(sessions) as session:
        reference = await persist_document(
            session,
            services.storage,
            attempt.run_id,
            name="report.md",
            text="# a report\n" * 20,
            content_type="text/markdown",
            inline_max_bytes=8,
        )
        uri = reference.uri
        artifact_id = reference.id

    assert uri is not None
    await services.storage.delete(uri)

    async with sessions() as session:
        document = await session.get(ArtifactRef, artifact_id)
        assert document is not None
        with pytest.raises(ObjectMissing) as raised:
            await load_document(services.storage, document)

    assert raised.value.params["attempt"] == "-"
    assert raised.value.params["run"] == str(attempt.run_id)


async def test_a_stored_artifact_is_streamed_only_once_storage_answers_for_it(
    sessions: async_sessionmaker[AsyncSession], services: Any
) -> None:
    """The refusal lands before the stream opens, so a reader never starts a body that breaks."""
    attempt = await make_attempt(sessions)
    payload = {"rows": ["y" * 100 for _ in range(50)]}
    async with session_scope(sessions) as session:
        stored = await session.get(StepAttempt, attempt.id)
        assert stored is not None
        reference = await persist_output(session, services.storage, stored, payload, inline_max_bytes=64)
        artifact_id, uri = reference.id, reference.uri

    async with sessions() as session:
        found = await session.get(ArtifactRef, artifact_id)
        assert found is not None
        chunks = [chunk async for chunk in await open_artifact(services.storage, found)]
        assert json.loads(b"".join(chunks)) == payload

        assert uri is not None
        await services.storage.delete(uri)
        with pytest.raises(ObjectMissing):
            await open_artifact(services.storage, found)
