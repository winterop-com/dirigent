"""The S3-compatible server the storage lane runs against, and the config that reaches it."""

import asyncio
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import suppress
from typing import Any, Final

import pytest
from pydantic import SecretStr

from dirigent_storage_s3 import MULTIPART_THRESHOLD, S3StorageBackend, S3StorageConfig, open_client

S3_IMAGE: Final = "rustfs/rustfs:1.0.0-rc.4"

S3_PORT: Final = 9000

#: Must match the credential in examples/s3/s3-round-trip.yaml for that example to run.
ACCESS_KEY: Final = "dirigent-test-key"
SECRET_KEY: Final = "dirigent-test-secret"

STARTUP_TIMEOUT: Final = 60.0

STARTUP_INTERVAL: Final = 0.25

BUCKET: Final = "dirigent-test"

LARGE_SIZE: Final = MULTIPART_THRESHOLD + 1024 * 1024

BLOCK_WIDTH: Final = 8


def payload(size: int) -> bytes:
    """Build a deterministic payload whose every block encodes its own offset, so misordering shows."""
    blocks = b"".join(index.to_bytes(BLOCK_WIDTH, "big") for index in range(size // BLOCK_WIDTH + 1))
    return blocks[:size]


def uri(key: str) -> str:
    """Address a key in the test bucket."""
    return f"s3://{BUCKET}/{key}"


async def create_bucket(config: S3StorageConfig) -> None:
    """Create the test bucket, tolerating a server that already has it."""
    async with open_client(config) as client:
        with suppress(Exception):
            await client.create_bucket(Bucket=BUCKET)


def wait_until_answering(url: str) -> None:
    """Poll the endpoint until it speaks S3 at all, which is what readiness means here.

    An unauthenticated request is refused, and a refusal is the proof: the server is up,
    routing, and signing.
    """
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2).close()  # noqa: S310 - a fixed http:// probe
            return
        except urllib.error.HTTPError:
            return
        except OSError:
            time.sleep(STARTUP_INTERVAL)
    raise TimeoutError(f"{url} did not answer within {STARTUP_TIMEOUT:.0f}s")


async def pending_uploads(config: S3StorageConfig, key: str) -> list[Any]:
    """List the multipart uploads the server still holds open for one key."""
    async with open_client(config) as client:
        listed: Any = await client.list_multipart_uploads(Bucket=BUCKET, Prefix=key)
    return list(listed.get("Uploads", []))


@pytest.fixture(scope="session")
def s3_server(request: pytest.FixtureRequest) -> Iterator[str]:
    """Start one S3-compatible server for the whole session, and yield its endpoint URL."""
    module = pytest.importorskip("testcontainers.core.container")
    container: Any = (
        module.DockerContainer(S3_IMAGE)
        .with_env("RUSTFS_ACCESS_KEY", ACCESS_KEY)
        .with_env("RUSTFS_SECRET_KEY", SECRET_KEY)
        .with_exposed_ports(S3_PORT)
    )
    try:
        container.start()
    except Exception as error:
        pytest.skip(f"the S3 server could not start, Docker is likely unreachable: {type(error).__name__}: {error}")
    request.addfinalizer(container.stop)
    endpoint = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(S3_PORT)}"
    wait_until_answering(f"{endpoint}/")
    yield endpoint


@pytest.fixture(scope="session")
def config(s3_server: str) -> S3StorageConfig:
    """Point a config at the running server, with the test bucket already created."""
    built = S3StorageConfig(
        endpoint_url=s3_server,
        access_key_id=ACCESS_KEY,
        secret_access_key=SecretStr(SECRET_KEY),
        path_style=True,
        bucket=BUCKET,
    )
    asyncio.run(create_bucket(built))
    return built


@pytest.fixture
def backend(config: S3StorageConfig) -> S3StorageBackend:
    """Bind a backend to the running server."""
    return S3StorageBackend(config)
