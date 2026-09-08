"""A storage URI as a block declares it, so an instance can check the scheme before a run."""

from typing import Annotated, Final

from pydantic import Field

#: The JSON Schema ``format`` a storage URI is published under. A document's value for a field
#: carrying it is checked against the schemes this instance's backends claim, at apply, rather
#: than failing the first time a step runs.
STORAGE_URI_FORMAT: Final = "storage-uri"

#: A URI addressing stored bytes: ``file://`` or ``s3://``, whatever a backend registered.
#:
#: The marker is what tells a validator this string is storage and not, say, the URL an HTTP
#: request is sent to. Nothing distinguishes the two by looking.
StorageUri = Annotated[str, Field(json_schema_extra={"format": STORAGE_URI_FORMAT})]
