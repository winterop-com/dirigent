"""Persisting a step's output as an artifact reference: inline when small, a URI when not."""

import hashlib
import json
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_common import JsonMap
from dirigent_core.errors import DomainError
from dirigent_core.messages import OBJECT_MISSING
from dirigent_core.models import ArtifactRef, StepAttempt
from dirigent_core.storage import Storage, StorageError, join_uri, parse_uri

JSON_CONTENT_TYPE = "application/json"

MARKDOWN_CONTENT_TYPE: Final = "text/markdown"

#: The key a text document inlines under, so an inline row is still a JSON document.
TEXT_KEY: Final = "text"

#: What an artifact row belonging to the run rather than to a step attempt names as its attempt.
NO_ATTEMPT: Final = "-"


class ObjectMissing(DomainError):
    """The object this row names is not in storage."""

    status = 404
    message = OBJECT_MISSING

    def __init__(self, reference: ArtifactRef) -> None:
        """Name the object that is gone, and the run and attempt whose row still names it."""
        super().__init__(
            uri=reference.uri or "",
            run=str(reference.run_id),
            attempt=str(reference.step_attempt_id) if reference.step_attempt_id else NO_ATTEMPT,
        )


def canonical_json(value: object) -> bytes:
    """Serialize a value the one way the engine hashes and stores it."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def digest_of(payload: bytes) -> str:
    """Hash a payload the way every digest column in the schema is written."""
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


async def persist_output(
    session: AsyncSession,
    storage: Storage,
    attempt: StepAttempt,
    output: JsonMap,
    *,
    inline_max_bytes: int,
) -> ArtifactRef:
    """Record a step output, inline or as a stored object, and return its reference.

    The attempt keeps the structured value either way, so reference resolution reads it
    straight off the row.
    """
    payload = canonical_json(output)
    reference = ArtifactRef(
        run_id=attempt.run_id,
        step_attempt_id=attempt.id,
        step_name=attempt.step_name,
        content_type=JSON_CONTENT_TYPE,
        size_bytes=len(payload),
        digest=digest_of(payload),
    )
    if len(payload) <= inline_max_bytes:
        reference.inline_value = output
    else:
        uri = join_uri(storage.scratch_for(attempt.run_id), "outputs", f"{attempt.id}.json")
        await storage.write_bytes(uri, payload)
        reference.uri = uri
        reference.scheme = parse_uri(uri)[0]
    session.add(reference)
    await session.flush()
    attempt.output = output
    attempt.output_artifact_id = reference.id
    return reference


async def persist_document(
    session: AsyncSession,
    storage: Storage,
    run_id: UUID,
    *,
    name: str,
    text: str,
    content_type: str,
    inline_max_bytes: int,
    existing: ArtifactRef | None = None,
) -> ArtifactRef:
    """Record a run-level text document, inline or as a stored object, and return its reference.

    ``existing`` is updated in place rather than replaced, so a link to the document survives
    a run that settles a second time.
    """
    payload = text.encode()
    reference = existing or ArtifactRef(run_id=run_id)
    stale = reference.uri
    reference.content_type = content_type
    reference.size_bytes = len(payload)
    reference.digest = digest_of(payload)
    if len(payload) <= inline_max_bytes:
        reference.inline_value = {TEXT_KEY: text}
        reference.uri = None
        reference.scheme = None
    else:
        uri = join_uri(storage.scratch_for(run_id), name)
        await storage.write_bytes(uri, payload)
        reference.inline_value = None
        reference.uri = uri
        reference.scheme = parse_uri(uri)[0]
    if stale is not None and stale != reference.uri:
        # The row no longer names the object, so nothing would ever read or sweep it again.
        with suppress(StorageError, OSError):
            await storage.delete(stale)
    if existing is None:
        session.add(reference)
    await session.flush()
    return reference


async def _present_uri(storage: Storage, reference: ArtifactRef) -> str:
    """Return the URI a row names once storage confirms the object is there, or refuse.

    A database restored without the artifact root it was taken beside still holds every row,
    so the object is stat-ed before it is opened: a read that refuses here names what is gone,
    where one that opened the stream first would break mid-body with the status already sent.
    """
    uri = reference.uri or ""
    if await storage.stat(uri) is None:
        raise ObjectMissing(reference)
    return uri


async def open_artifact(storage: Storage, reference: ArtifactRef) -> AsyncGenerator[bytes]:
    """Open the stored object a row names for streaming, refusing before the first byte."""
    return storage.open_read(await _present_uri(storage, reference))


async def load_document(storage: Storage, reference: ArtifactRef) -> str:
    """Read a text document back, from the row when it inlined and from storage when it did not."""
    if reference.inline_value is not None:
        inlined = reference.inline_value.get(TEXT_KEY)
        return inlined if isinstance(inlined, str) else ""
    if reference.uri is None:
        return ""
    return (await storage.read_bytes(await _present_uri(storage, reference))).decode()


async def load_artifact(session: AsyncSession, storage: Storage, artifact_id: UUID) -> JsonMap | None:
    """Read an artifact back, from the row when it inlined and from storage when it did not."""
    reference = await session.get(ArtifactRef, artifact_id)
    if reference is None:
        return None
    if reference.inline_value is not None:
        return reference.inline_value
    if reference.uri is None:
        return None
    payload = await storage.read_bytes(await _present_uri(storage, reference))
    loaded: JsonMap = json.loads(payload)
    return loaded
