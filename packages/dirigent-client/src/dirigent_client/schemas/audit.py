"""The audit trail: who changed what, and when, as a reading of it answers."""

from datetime import datetime
from uuid import UUID

from dirigent_client.enums import AuditAction, AuditSubject
from dirigent_client.schemas.common import WireModel


class AuditEntryOut(WireModel):
    """One administrative change. An update names the fields it changed, and never a value."""

    id: int
    created_at: datetime
    action: AuditAction
    subject_kind: AuditSubject
    subject_id: UUID | None = None
    subject_code: str | None = None
    parent_code: str | None = None
    """The code of what the subject belongs to: a schedule's or a source's pipeline, a token's account."""

    fields: list[str] = []
    actor_id: UUID | None = None
    actor_username: str | None = None
    actor_token: str | None = None
    """The API token the account acted through, or null for a browser session or the host."""

    actor_token_prefix: str | None = None
    actor_label: str
    """Who acted, as a run's attribution renders it: ``agent (token mcp-trial)``, or ``dg admin``."""
