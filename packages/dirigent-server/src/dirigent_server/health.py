"""The liveness and readiness probes, and the checks readiness runs."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import ClassVar

from fastapi import APIRouter, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncEngine

from dirigent_client.schemas import CheckResult, CheckStatus, Health, Readiness
from dirigent_core.database import ping

router = APIRouter(tags=["health"])


#: Aggregation takes the maximum, so a new status must sort worse than every status it
#: outranks.
_SEVERITY: dict[CheckStatus, int] = {
    CheckStatus.HEALTHY: 0,
    CheckStatus.DEGRADED: 1,
    CheckStatus.UNHEALTHY: 2,
}


class HealthCheck(ABC):
    """One named dependency the readiness probe verifies."""

    name: ClassVar[str]

    @abstractmethod
    async def check(self) -> CheckResult:
        """Verify the dependency, returning a result rather than raising."""
        ...


class DatabaseHealthCheck(HealthCheck):
    """Verifies that the database answers a trivial query."""

    name = "database"

    def __init__(self, engine: AsyncEngine) -> None:
        """Bind the check to the process's engine."""
        self._engine = engine

    async def check(self) -> CheckResult:
        """Run SELECT 1 through the async engine."""
        if await ping(self._engine):
            return CheckResult(status=CheckStatus.HEALTHY)
        return CheckResult(status=CheckStatus.UNHEALTHY, detail="database is unreachable")


type HealthCheckRegistry = Mapping[str, HealthCheck]


def build_registry(engine: AsyncEngine) -> dict[str, HealthCheck]:
    """Assemble the checks this process runs."""
    checks: list[HealthCheck] = [DatabaseHealthCheck(engine)]
    return {check.name: check for check in checks}


def aggregate(results: Mapping[str, CheckResult]) -> CheckStatus:
    """Reduce a set of results to the worst status; no checks means healthy."""
    if not results:
        return CheckStatus.HEALTHY
    return max(results.values(), key=lambda result: _SEVERITY[result.status]).status


async def run_checks(registry: HealthCheckRegistry) -> dict[str, CheckResult]:
    """Run every registered check concurrently, turning a raised error into unhealthy."""

    async def run(check: HealthCheck) -> CheckResult:
        try:
            return await check.check()
        except Exception as error:
            return CheckResult(status=CheckStatus.UNHEALTHY, detail=f"{type(error).__name__}: {error}")

    names = list(registry)
    results = await asyncio.gather(*(run(registry[name]) for name in names))
    return dict(zip(names, results, strict=True))


@router.get("/health", operation_id="health", response_model=Health, summary="Liveness")
async def health(request: Request) -> Health:
    """Report that the process is alive, without touching any dependency."""
    return Health(version=request.app.state.version)


@router.get("/health/ready", operation_id="readiness", response_model=Readiness, summary="Readiness")
async def health_ready(request: Request, response: Response) -> Readiness:
    """Run every registered check and report the worst status, with 503 when unhealthy."""
    registry: HealthCheckRegistry = request.app.state.health_checks
    results = await run_checks(registry)
    overall = aggregate(results)
    if overall is CheckStatus.UNHEALTHY:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Readiness(status=overall, checks=results)
