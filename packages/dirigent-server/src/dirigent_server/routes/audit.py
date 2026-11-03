"""The audit trail: every administrative change, newest first, for admins only."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from dirigent_client.enums import AuditAction, AuditSubject
from dirigent_client.schemas import AuditEntryOut, Page
from dirigent_core.audit import AuditQuery, list_entries
from dirigent_server.dependencies import SessionDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip, int_cursor
from dirigent_server.security import AdminDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["audit"])


@router.get(
    "/audit", operation_id="listAudit", summary="List administrative changes", response_model=Page[AuditEntryOut]
)
async def list_audit(
    session: SessionDep,
    principal: AdminDep,
    subject_kind: Annotated[AuditSubject | None, Query(description="Only changes to this kind of thing.")] = None,
    subject: Annotated[str | None, Query(description="Only changes to the subject with this code.")] = None,
    actor: Annotated[
        str | None, Query(description="Only changes by this username, or by this host command when no account acted.")
    ] = None,
    action: Annotated[AuditAction | None, Query(description="Only changes of this action.")] = None,
    since: Annotated[datetime | None, Query(description="Only changes at or after this instant.")] = None,
    until: Annotated[datetime | None, Query(description="Only changes before this instant.")] = None,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[AuditEntryOut]:
    """Read who changed what, newest first. An update names the fields it changed and never a value."""
    query = AuditQuery(subject_kind=subject_kind, subject=subject, actor=actor, action=action, since=since, until=until)
    rows = await list_entries(session, query, after=int_cursor(after), limit=limit + 1)
    found = [AuditEntryOut.model_validate(row, from_attributes=True) for row in rows]
    items, following = clip(found, limit, lambda row: row.id)
    return Page(items=items, next=following)
