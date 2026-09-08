"""The ``s3://`` storage backend: streamed bytes against AWS S3 or any S3-compatible endpoint."""

import fnmatch
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from typing import Any, ClassVar, Final, cast
from urllib.parse import urlsplit

import aioboto3

# botocore ships no py.typed, and the workspace mypy config only exempts ``aioboto3.*``.
from botocore.config import Config  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from pydantic import BaseModel, SecretStr

from dirigent_common import BlockModel
from dirigent_plugin import ByteSink, StatResult, StorageBackend

SCHEME: Final = "s3"

SERVICE_NAME: Final = "s3"

CHUNK_SIZE: Final = 256 * 1024

#: The smallest part S3 accepts in a multipart upload, for every part except the last.
MINIMUM_PART_SIZE: Final = 5 * 1024 * 1024

PART_SIZE: Final = MINIMUM_PART_SIZE

MULTIPART_THRESHOLD: Final = PART_SIZE

GLOB_CHARACTERS: Final = ("*", "?", "[")

#: The error codes S3 answers a head or a delete of something absent with.
MISSING_CODES: Final = frozenset({"404", "NoSuchKey", "NoSuchBucket", "NotFound"})

PATH_ADDRESSING: Final = "path"

VIRTUAL_ADDRESSING: Final = "virtual"

#: Typed ``Any`` because neither aioboto3 nor botocore ships type information.
type S3Client = Any


class S3StorageError(Exception):
    """Any failure raised by the s3 backend itself, as opposed to by the S3 API."""


class InvalidS3Uri(S3StorageError):
    """A URI handed to this backend is not an addressable ``s3://bucket/key``."""

    def __init__(self, uri: str, reason: str) -> None:
        """Name the URI and exactly what is wrong with it, because this is a document error."""
        super().__init__(f"{uri!r} is not a usable {SCHEME} URI: {reason}")
        self.uri = uri
        self.reason = reason


class S3StorageConfig(BlockModel):
    """Everything the backend needs to reach one S3 or S3-compatible endpoint."""

    endpoint_url: str | None = None
    """The service root, set for any S3-compatible endpoint; None means AWS S3 itself."""

    region: str = "us-east-1"
    """The region signed into every request."""

    access_key_id: str | None = None
    """The public half of the credential; None falls back to the ambient AWS chain."""

    secret_access_key: SecretStr | None = None
    """The secret half of the credential, redacted by the API and encrypted at rest."""

    path_style: bool = False
    """Whether buckets are addressed as a path segment, which every S3 clone needs."""

    verify_tls: bool = True
    """Whether certificates are verified; turning this off is a per-connection decision."""

    bucket: str | None = None
    """The bucket a connection check probes; addressing still carries the bucket in the URI."""


def parse_s3_uri(uri: str) -> tuple[str, str]:
    """Split an ``s3://bucket/key`` URI into its bucket and its key, or refuse it."""
    split = urlsplit(uri)
    if not split.scheme:
        raise InvalidS3Uri(uri, "it names no scheme")
    if split.scheme != SCHEME:
        raise InvalidS3Uri(uri, f"expected scheme {SCHEME!r}, got {split.scheme!r}")
    if split.query or split.fragment:
        raise InvalidS3Uri(uri, "a key may contain '?' and '#', so neither may be a URI delimiter here")
    bucket = split.netloc
    if not bucket:
        raise InvalidS3Uri(uri, "it names no bucket")
    if ":" in bucket or "@" in bucket:
        raise InvalidS3Uri(uri, f"the authority {bucket!r} is not a bare bucket name")
    return bucket, split.path.lstrip("/")


def object_uri(bucket: str, key: str) -> str:
    """Render a bucket and key back as the URI a caller would use."""
    return f"{SCHEME}://{bucket}/{key}"


def is_pattern(location: str) -> bool:
    """Report whether a listing location is a glob rather than a plain key prefix."""
    return any(character in location for character in GLOB_CHARACTERS)


def fixed_prefix(pattern: str) -> str:
    """Return the leading run of a pattern before its first glob character, for the S3 ``Prefix``."""
    for index, character in enumerate(pattern):
        if character in GLOB_CHARACTERS:
            return pattern[:index]
    return pattern


def matches_pattern(key: str, pattern: str) -> bool:
    """Decide whether a key belongs in a listing: prefix when plain, ``fnmatch`` when a glob.

    ``fnmatch`` is deliberate, and differs from the ``file://`` backend's ``Path.full_match``.
    An S3 key is one flat string and not a path, so ``*`` matches across ``/`` here: listing
    ``s3://bucket/data/*.csv`` finds ``data/2026/01/rows.csv`` as well as ``data/rows.csv``.
    That keeps a plain prefix listing and a glob listing consistent, since a prefix already
    reaches every depth below it.
    """
    if not is_pattern(pattern):
        return key.startswith(pattern)
    return fnmatch.fnmatchcase(key, pattern)


def client_kwargs(config: S3StorageConfig) -> dict[str, Any]:
    """Build the keyword arguments one S3 client is opened with."""
    addressing = PATH_ADDRESSING if config.path_style else VIRTUAL_ADDRESSING
    kwargs: dict[str, Any] = {
        "service_name": SERVICE_NAME,
        "region_name": config.region,
        "config": Config(s3={"addressing_style": addressing}),
        "verify": config.verify_tls,
    }
    if config.endpoint_url is not None:
        kwargs["endpoint_url"] = config.endpoint_url
    if config.access_key_id is not None:
        kwargs["aws_access_key_id"] = config.access_key_id
    if config.secret_access_key is not None:
        kwargs["aws_secret_access_key"] = config.secret_access_key.get_secret_value()
    return kwargs


def open_client(config: S3StorageConfig) -> AbstractAsyncContextManager[S3Client]:
    """Open an S3 client carrying a connection's endpoint, region, credentials, and TLS setting."""
    session: Any = aioboto3.Session()
    return cast(AbstractAsyncContextManager[S3Client], session.client(**client_kwargs(config)))


def is_missing(error: ClientError) -> bool:
    """Report whether a client error is S3 saying the object or bucket simply is not there."""
    response: dict[str, Any] = getattr(error, "response", None) or {}
    details: dict[str, Any] = response.get("Error") or {}
    return str(details.get("Code", "")) in MISSING_CODES


class S3Sink:
    """The write end of an S3 object: buffered, and promoted to a multipart upload once large."""

    def __init__(self, client: S3Client, bucket: str, key: str) -> None:
        """Hold the open client and the object the accumulated bytes will be published as."""
        self._client = client
        self.bucket = bucket
        self.key = key
        self.written = 0
        self._buffer = bytearray()
        self._parts: list[dict[str, Any]] = []
        self._upload_id: str | None = None

    @property
    def upload_id(self) -> str | None:
        """Return the multipart upload id, which is None while the write still fits one put."""
        return self._upload_id

    async def write(self, data: bytes) -> int:
        """Buffer bytes, sending out a part whenever enough of them have accumulated."""
        self._buffer.extend(data)
        self.written += len(data)
        while len(self._buffer) >= MULTIPART_THRESHOLD:
            await self._send_part()
        return len(data)

    async def close(self) -> None:
        """Publish the object: one put for a small write, a completed upload for a multipart one."""
        if self._upload_id is None:
            await self._client.put_object(Bucket=self.bucket, Key=self.key, Body=bytes(self._buffer))
            self._buffer.clear()
            return
        if self._buffer:
            await self._send_part()
        await self._client.complete_multipart_upload(
            Bucket=self.bucket,
            Key=self.key,
            UploadId=self._upload_id,
            MultipartUpload={"Parts": self._parts},
        )
        self._upload_id = None

    async def abort(self) -> None:
        """Discard an in-flight multipart upload, so a failed write leaves no object behind."""
        if self._upload_id is None:
            return
        # A failed abort must not mask the failure that caused it; S3 expires the upload anyway.
        with suppress(ClientError):
            await self._client.abort_multipart_upload(Bucket=self.bucket, Key=self.key, UploadId=self._upload_id)
        self._upload_id = None

    async def _send_part(self) -> None:
        """Upload one part off the front of the buffer, starting the multipart upload if needed."""
        if self._upload_id is None:
            started: Any = await self._client.create_multipart_upload(Bucket=self.bucket, Key=self.key)
            self._upload_id = str(started["UploadId"])
        chunk = bytes(self._buffer[:PART_SIZE])
        del self._buffer[:PART_SIZE]
        number = len(self._parts) + 1
        uploaded: Any = await self._client.upload_part(
            Bucket=self.bucket,
            Key=self.key,
            UploadId=self._upload_id,
            PartNumber=number,
            Body=chunk,
        )
        self._parts.append({"ETag": str(uploaded["ETag"]), "PartNumber": number})


class S3StorageBackend(StorageBackend):
    """Streams bytes to and from an S3 bucket, or anything else that speaks the S3 API."""

    scheme: ClassVar[str] = SCHEME
    config_model: ClassVar[type[BaseModel]] = S3StorageConfig

    def __init__(self, config: S3StorageConfig | None = None) -> None:
        """Bind the backend to the endpoint and credentials every ``s3://`` URI is served from."""
        self.config = config if config is not None else S3StorageConfig()

    def configured(self, config: BaseModel) -> "S3StorageBackend":
        """Return a backend bound to the connection this instance configures ``s3://`` from."""
        return S3StorageBackend(S3StorageConfig.model_validate(config.model_dump()))

    def locate(self, uri: str, *, require_key: bool = True) -> tuple[str, str]:
        """Resolve a URI to the bucket and key it addresses, refusing one that names no object."""
        bucket, key = parse_s3_uri(uri)
        if require_key and not key:
            raise InvalidS3Uri(uri, "it names a bucket but no key")
        return bucket, key

    def uri_for(self, bucket: str, key: str) -> str:
        """Render a bucket and key back as the URI a caller would use."""
        return object_uri(bucket, key)

    def client(self) -> AbstractAsyncContextManager[S3Client]:
        """Open an S3 client from this backend's connection settings."""
        return open_client(self.config)

    async def open_read(self, uri: str) -> AsyncGenerator[bytes]:
        """Stream the object at a URI in bounded chunks, never holding the whole body."""
        bucket, key = self.locate(uri)
        async with self.client() as client:
            response: Any = await client.get_object(Bucket=bucket, Key=key)
            body: Any = response["Body"]
            while True:
                chunk: bytes = await body.read(CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk

    @asynccontextmanager
    async def _writer(self, uri: str) -> AsyncGenerator[ByteSink]:
        """Open a buffered writer, publishing the object only once writing finished cleanly."""
        bucket, key = self.locate(uri)
        async with self.client() as client:
            sink = S3Sink(client, bucket, key)
            try:
                yield sink
                # Inside the guard, so a failure while sending the last part or completing the
                # upload leaves no multipart upload outstanding.
                await sink.close()
            except BaseException:
                await sink.abort()
                raise

    def open_write(self, uri: str) -> AbstractAsyncContextManager[ByteSink]:
        """Open a streamed writer for a URI; the object appears only once writing finished."""
        return self._writer(uri)

    async def stat(self, uri: str) -> StatResult | None:
        """Describe the object at a URI, or return None when it does not exist."""
        bucket, key = self.locate(uri)
        async with self.client() as client:
            try:
                head: Any = await client.head_object(Bucket=bucket, Key=key)
            except ClientError as error:
                if is_missing(error):
                    return None
                raise
        return StatResult(
            uri=self.uri_for(bucket, key),
            size=int(head["ContentLength"]),
            modified_at=head["LastModified"],
            content_type=head.get("ContentType"),
        )

    async def list(self, uri: str) -> AsyncIterator[StatResult]:
        """List the objects under a key prefix, or the objects matching a glob pattern."""
        bucket, pattern = self.locate(uri, require_key=False)
        async with self.client() as client:
            paginator: Any = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=bucket, Prefix=fixed_prefix(pattern)):
                entries: Any = page.get("Contents", [])
                for entry in cast(list[Any], entries):
                    key = str(entry["Key"])
                    if matches_pattern(key, pattern):
                        yield StatResult(
                            uri=self.uri_for(bucket, key),
                            size=int(entry["Size"]),
                            modified_at=entry["LastModified"],
                        )

    async def delete(self, uri: str) -> None:
        """Remove the object at a URI; deleting what is not there is not an error."""
        bucket, key = self.locate(uri)
        async with self.client() as client:
            try:
                await client.delete_object(Bucket=bucket, Key=key)
            except ClientError as error:
                if not is_missing(error):
                    raise
