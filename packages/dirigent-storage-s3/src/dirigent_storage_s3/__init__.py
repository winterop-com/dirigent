"""The ``s3://`` storage plugin: one backend and the connection kind it is configured from."""

from dirigent_plugin import Contribution, extension
from dirigent_storage_s3.backend import (
    CHUNK_SIZE,
    GLOB_CHARACTERS,
    MINIMUM_PART_SIZE,
    MISSING_CODES,
    MULTIPART_THRESHOLD,
    PART_SIZE,
    PATH_ADDRESSING,
    SCHEME,
    VIRTUAL_ADDRESSING,
    InvalidS3Uri,
    S3Client,
    S3Sink,
    S3StorageBackend,
    S3StorageConfig,
    S3StorageError,
    client_kwargs,
    fixed_prefix,
    is_missing,
    is_pattern,
    matches_pattern,
    object_uri,
    open_client,
    parse_s3_uri,
)
from dirigent_storage_s3.connection import S3ConnectionKind


class S3StoragePlugin:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the ``s3://`` storage backend and the ``s3`` connection kind it reads."""
        return Contribution(
            storage_backends=[S3StorageBackend()],
            connection_kinds=[S3ConnectionKind()],
        )


plugin = S3StoragePlugin()

__all__ = [
    "CHUNK_SIZE",
    "GLOB_CHARACTERS",
    "MINIMUM_PART_SIZE",
    "MISSING_CODES",
    "MULTIPART_THRESHOLD",
    "PART_SIZE",
    "PATH_ADDRESSING",
    "SCHEME",
    "VIRTUAL_ADDRESSING",
    "InvalidS3Uri",
    "S3Client",
    "S3ConnectionKind",
    "S3Sink",
    "S3StorageBackend",
    "S3StorageConfig",
    "S3StorageError",
    "S3StoragePlugin",
    "client_kwargs",
    "fixed_prefix",
    "is_missing",
    "is_pattern",
    "matches_pattern",
    "object_uri",
    "open_client",
    "parse_s3_uri",
    "plugin",
]
