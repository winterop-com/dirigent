"""Tests for the S3 write end that need no S3 API: what a failed abort does to the failure it follows."""

from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError  # type: ignore[import-untyped]

from dirigent_storage_s3 import S3Sink

PART: Any = {"ETag": '"part"'}


class UnreachableAbort:
    """An S3 client whose upload starts and parts land, and whose abort cannot reach the endpoint."""

    def __init__(self, abort_error: Exception) -> None:
        """Hold the error the abort raises."""
        self.abort_error = abort_error
        self.aborted = 0

    async def create_multipart_upload(self, **_: Any) -> Any:
        return {"UploadId": "upload-1"}

    async def upload_part(self, **_: Any) -> Any:
        return PART

    async def abort_multipart_upload(self, **_: Any) -> Any:
        self.aborted += 1
        raise self.abort_error


@pytest.mark.parametrize(
    "abort_error",
    [
        EndpointConnectionError(endpoint_url="http://127.0.0.1:9"),
        ClientError({"Error": {"Code": "InternalError", "Message": "try again"}}, "AbortMultipartUpload"),
        ConnectionResetError("the endpoint hung up"),
    ],
)
async def test_an_abort_that_fails_leaves_the_write_failure_in_place(abort_error: Exception) -> None:
    client = UnreachableAbort(abort_error)
    sink = S3Sink(client, "bucket", "key")
    await sink._send_part()  # pyright: ignore[reportPrivateUsage] - starts the upload an abort discards
    assert sink.upload_id == "upload-1"

    with pytest.raises(RuntimeError, match="mid-write"):
        try:
            raise RuntimeError("mid-write")
        except RuntimeError:
            await sink.abort()
            raise

    assert client.aborted == 1
    assert sink.upload_id is None
