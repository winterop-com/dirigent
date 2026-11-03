"""The audit trail: every administrative change, newest first. Admin only."""

from datetime import datetime

from dirigent_client.enums import AuditAction, AuditSubject
from dirigent_client.resources.base import Resource, query
from dirigent_client.schemas import AuditEntryOut, Page


class Audit(Resource):
    """Read who changed what on an instance."""

    async def list(
        self,
        *,
        subject_kind: AuditSubject | None = None,
        subject: str | None = None,
        actor: str | None = None,
        action: AuditAction | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        after: str | None = None,
        limit: int | None = None,
    ) -> Page[AuditEntryOut]:
        """List the changes newest first, narrowed by subject, actor, action and a half-open time window."""
        params = query(
            subject_kind=subject_kind.value if subject_kind else None,
            subject=subject,
            actor=actor,
            action=action.value if action else None,
            since=since.isoformat() if since else None,
            until=until.isoformat() if until else None,
            after=after,
            limit=limit,
        )
        return await self._many(AuditEntryOut, "GET", "/audit", params=params)
