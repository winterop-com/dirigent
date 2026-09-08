"""Persisting a step's output as an artifact reference: inline when small, a URI when not."""

import hashlib
import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from dirigent_common import JsonMap
from dirigent_core.models import ArtifactRef, StepAttempt
from dirigent_core.storage import Storage, join_uri, parse_uri

JSON_CONTENT_TYPE = "application/json"


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


async def load_artifact(session: AsyncSession, storage: Storage, artifact_id: UUID) -> JsonMap | None:
    """Read an artifact back, from the row when it inlined and from storage when it did not."""
    reference = await session.get(ArtifactRef, artifact_id)
    if reference is None:
        return None
    if reference.inline_value is not None:
        return reference.inline_value
    if reference.uri is None:
        return None
    payload = await storage.read_bytes(reference.uri)
    loaded: JsonMap = json.loads(payload)
    return loaded
