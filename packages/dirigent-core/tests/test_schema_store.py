"""Storing named JSON Schemas: identity from the schema's own keywords, and the validity gate."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_core.database import session_scope
from dirigent_core.schemas import (
    SchemaRefused,
    check_valid_schema,
    code_from_id,
    resolve_identity,
    schema_codes,
    store_schema,
)

ORG_UNIT = {
    "$id": "org-unit",
    "title": "Organisation unit",
    "description": "An org unit as the metadata read returns it.",
    "type": "object",
    "required": ["id", "displayName"],
    "properties": {"id": {"type": "string"}, "displayName": {"type": "string"}},
}


def test_code_from_id_takes_the_last_segment_without_extension() -> None:
    assert code_from_id("https://dirigent/schemas/org-unit.json") == "org-unit"
    assert code_from_id("org-unit") == "org-unit"
    assert code_from_id("Not A Code") is None


def test_identity_is_read_from_the_schemas_own_keywords() -> None:
    code, name, description = resolve_identity(ORG_UNIT, code=None, name=None, description=None)
    assert code == "org-unit"
    assert name == "Organisation unit"
    assert description == "An org unit as the metadata read returns it."


def test_an_explicit_code_wins_over_the_dollar_id() -> None:
    code, _, _ = resolve_identity(ORG_UNIT, code="given", name=None, description=None)
    assert code == "given"


def test_a_filename_is_the_last_fallback_when_there_is_no_id() -> None:
    bare = {"type": "object"}
    code, _, _ = resolve_identity(bare, code=None, name=None, description=None, fallback_code="from-file")
    assert code == "from-file"


def test_a_schema_that_names_no_code_any_way_is_refused() -> None:
    with pytest.raises(SchemaRefused):
        resolve_identity({"type": "object"}, code=None, name=None, description=None)


def test_a_body_that_is_not_a_valid_schema_is_refused_naming_the_fault() -> None:
    with pytest.raises(SchemaRefused) as refused:
        check_valid_schema({"type": "not-a-type"})
    assert "not a valid JSON Schema" in str(refused.value)


async def test_store_reads_identity_and_a_second_store_replaces_by_code(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        row = await store_schema(session, ORG_UNIT)
        assert row.code == "org-unit"
        assert row.name == "Organisation unit"
    async with session_scope(sessions) as session:
        again = await store_schema(session, {**ORG_UNIT, "description": "reworded"})
        assert again.code == "org-unit"
        assert again.description == "reworded"
    async with session_scope(sessions) as session:
        assert await schema_codes(session) == {"org-unit"}


async def test_storing_an_invalid_schema_writes_nothing(sessions: async_sessionmaker[AsyncSession]) -> None:
    with pytest.raises(SchemaRefused):
        async with session_scope(sessions) as session:
            await store_schema(session, {"type": 5})
    async with session_scope(sessions) as session:
        assert await schema_codes(session) == set()


async def test_load_schemas_snapshots_every_body_by_code(sessions: async_sessionmaker[AsyncSession]) -> None:
    """What a claim hands a block is the whole table, code to body, as ``validate.schema`` reads it."""
    from dirigent_core.engine import load_schemas

    async with session_scope(sessions) as session:
        await store_schema(session, ORG_UNIT)
    async with session_scope(sessions) as session:
        loaded = await load_schemas(session)
    assert set(loaded) == {"org-unit"}
    assert loaded["org-unit"]["required"] == ["id", "displayName"]
