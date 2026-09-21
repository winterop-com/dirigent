"""Tests for the engine registry: what a backend dispatches to, and what may claim one."""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import ClassVar

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import URL, make_url

from dirigent_block_sql import engines
from dirigent_block_sql.engines import (
    DuplicateEngine,
    SqlAlchemyEngine,
    SqlEngine,
    SqlSession,
    engine_for,
    registry,
)
from dirigent_block_sql.sql import SqlConnectionConfig
from dirigent_common import HealthReport, JsonMap
from dirigent_plugin import StepContext, extension

#: A group no distribution registers, so a test sees only the plugins it is handed.
NO_GROUP = "dirigent.sql.engines.none"


class ToyEngine(SqlEngine):
    """An engine claiming a backend no installed package does."""

    backend: ClassVar[str] = "toy"

    def validate(self, settings: SqlConnectionConfig, url: URL) -> None:
        pass

    async def check(self, settings: SqlConnectionConfig, url: URL) -> HealthReport:
        return HealthReport(healthy=True, detail="toy answered")

    def session(
        self,
        settings: SqlConnectionConfig,
        url: URL,
        ctx: StepContext,
        *,
        statements: Sequence[str],
        params: JsonMap,
    ) -> AbstractAsyncContextManager[SqlSession]:
        raise NotImplementedError


class ToyPlugin:
    """A plugin object contributing the toy engine, as an installed package would."""

    @extension
    def engines(self) -> Sequence[SqlEngine]:
        return [ToyEngine()]


class NotAnEnginePlugin:
    """A plugin answering the hook with something that is not an engine."""

    @extension
    def engines(self) -> Sequence[SqlEngine]:
        return ["postgresql"]  # type: ignore[list-item]


def test_a_contributed_engine_is_what_its_backend_dispatches_to(monkeypatch: pytest.MonkeyPatch) -> None:
    found = registry(group=NO_GROUP, extra={"toy": ToyPlugin()})
    assert isinstance(found["toy"], ToyEngine)

    monkeypatch.setattr(engines, "_installed", lambda: found)
    assert isinstance(engine_for(make_url("toy:///warehouse.toy")), ToyEngine)


def test_a_backend_no_engine_claims_is_driven_through_sqlalchemy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engines, "_installed", lambda: registry(group=NO_GROUP))
    assert isinstance(engine_for(make_url("postgresql+asyncpg://user@host/db")), SqlAlchemyEngine)


def test_two_plugins_claiming_one_backend_are_refused_rather_than_ordered() -> None:
    with pytest.raises(DuplicateEngine) as raised:
        registry(group=NO_GROUP, extra={"one": ToyPlugin(), "two": ToyPlugin()})
    assert raised.value.backend == "toy"
    assert raised.value.plugins == ("one", "two")


def test_what_a_plugin_answers_with_that_is_not_an_engine_is_not_registered() -> None:
    assert registry(group=NO_GROUP, extra={"odd": NotAnEnginePlugin()}) == {}


def test_a_url_naming_an_engine_package_that_is_not_installed_names_the_install(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the engine there is no driver to write in the url either, so the refusal is the install."""
    monkeypatch.setattr(engines, "_installed", lambda: registry(group=NO_GROUP))
    with pytest.raises(ValidationError) as raised:
        SqlConnectionConfig(url="duckdb:///warehouse.duckdb")
    assert "uv pip install dirigent-block-duckdb" in str(raised.value)
