"""The ``s3`` connection kind: the named credential record the ``s3://`` backend is configured from."""

from typing import Any, ClassVar

from pydantic import BaseModel

from dirigent_common import HealthReport
from dirigent_plugin import ConnectionKind
from dirigent_storage_s3.backend import S3StorageConfig, open_client


class S3ConnectionKind(ConnectionKind):
    """The connection kind the ``s3://`` storage backend resolves its endpoint and credentials through."""

    id: ClassVar[str] = "s3"
    config_model: ClassVar[type[BaseModel]] = S3StorageConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """Probe the endpoint once and report whether it answered, never raising."""
        settings = S3StorageConfig.model_validate(config.model_dump())
        try:
            async with open_client(settings) as client:
                detail = await _probe(client, settings)
        # Broad on purpose: a health check reports a failure, it never raises one at the caller.
        except Exception as error:
            return HealthReport(healthy=False, detail=f"{type(error).__name__}: {error}")
        return HealthReport(healthy=True, detail=detail)


async def _probe(client: Any, config: S3StorageConfig) -> str:
    """Make the cheapest call that proves the connection works, and describe what it found."""
    if config.bucket:
        await client.head_bucket(Bucket=config.bucket)
        return f"bucket {config.bucket!r} reachable"
    listed: Any = await client.list_buckets()
    return f"{len(listed.get('Buckets', []))} buckets visible"
