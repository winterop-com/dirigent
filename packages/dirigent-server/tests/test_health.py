"""Tests for the health-check registry and how readiness aggregates it."""

from pathlib import Path

import pytest

from dirigent_core.config import Settings
from dirigent_core.database import create_engine
from dirigent_server.health import (
    CheckResult,
    CheckStatus,
    DatabaseHealthCheck,
    HealthCheck,
    aggregate,
    build_registry,
    run_checks,
)


class StubCheck(HealthCheck):
    """A check that reports whatever it was constructed with."""

    name = "stub"

    def __init__(self, result: CheckResult) -> None:
        """Fix the answer this check gives."""
        self._result = result

    async def check(self) -> CheckResult:
        """Return the fixed answer."""
        return self._result


class ExplodingCheck(HealthCheck):
    """A check that raises instead of reporting."""

    name = "exploding"

    async def check(self) -> CheckResult:
        """Fail loudly."""
        raise RuntimeError("dependency exploded")


def result(status: CheckStatus) -> CheckResult:
    """Build a bare result of a given status."""
    return CheckResult(status=status)


def test_no_checks_aggregate_to_healthy() -> None:
    assert aggregate({}) is CheckStatus.HEALTHY


def test_all_healthy_checks_aggregate_to_healthy() -> None:
    assert aggregate({"a": result(CheckStatus.HEALTHY), "b": result(CheckStatus.HEALTHY)}) is CheckStatus.HEALTHY


def test_healthy_plus_degraded_aggregates_to_degraded() -> None:
    assert aggregate({"a": result(CheckStatus.HEALTHY), "b": result(CheckStatus.DEGRADED)}) is CheckStatus.DEGRADED


def test_any_unhealthy_check_aggregates_to_unhealthy() -> None:
    results = {
        "a": result(CheckStatus.HEALTHY),
        "b": result(CheckStatus.DEGRADED),
        "c": result(CheckStatus.UNHEALTHY),
    }
    assert aggregate(results) is CheckStatus.UNHEALTHY


async def test_run_checks_runs_every_registered_check() -> None:
    registry: dict[str, HealthCheck] = {
        "one": StubCheck(result(CheckStatus.HEALTHY)),
        "two": StubCheck(CheckResult(status=CheckStatus.DEGRADED, detail="slow")),
    }
    results = await run_checks(registry)
    assert set(results) == {"one", "two"}
    assert results["two"].detail == "slow"
    assert aggregate(results) is CheckStatus.DEGRADED


async def test_a_raising_check_reports_unhealthy_rather_than_propagating() -> None:
    results = await run_checks({"exploding": ExplodingCheck()})
    assert results["exploding"].status is CheckStatus.UNHEALTHY
    assert "dependency exploded" in (results["exploding"].detail or "")


async def test_the_database_check_reports_a_reachable_database(tmp_path: Path) -> None:
    engine = create_engine(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}"))
    try:
        assert (await DatabaseHealthCheck(engine).check()).status is CheckStatus.HEALTHY
    finally:
        await engine.dispose()


async def test_the_database_check_reports_an_unreachable_database(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    engine = create_engine(Settings(database_url=f"sqlite+aiosqlite:///{blocker / 'dirigent.db'}"))
    try:
        outcome = await DatabaseHealthCheck(engine).check()
    finally:
        await engine.dispose()
    assert outcome.status is CheckStatus.UNHEALTHY
    assert outcome.detail == "database is unreachable"


def test_the_registry_is_keyed_by_check_name(tmp_path: Path) -> None:
    engine = create_engine(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'dirigent.db'}"))
    registry = build_registry(engine)
    assert set(registry) == {"database"}
    assert isinstance(registry["database"], DatabaseHealthCheck)


def test_a_health_check_must_implement_check() -> None:
    with pytest.raises(TypeError):
        HealthCheck()  # type: ignore[abstract]
