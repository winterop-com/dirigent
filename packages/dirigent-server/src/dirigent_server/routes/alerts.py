"""Alert rules, and the notification queue they deliver through."""

from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from dirigent_client.enums import NotificationStatus
from dirigent_client.schemas import (
    AlertRuleIn,
    AlertRuleOut,
    AlertRuleUpdate,
    NotificationOut,
    Page,
    TestQueued,
    TestRequest,
)
from dirigent_common.durations import format_duration
from dirigent_core.alerting import (
    AlertError,
    AlertRuleRequest,
    create_rule,
    delete_rule,
    find_notification,
    find_rule,
    list_notifications,
    list_rules,
    queue_test_message,
    retry_notification,
    set_paused,
)
from dirigent_core.models import AlertRule, Connection, Notification, Pipeline, Run
from dirigent_server.dependencies import ServicesDep, SessionDep
from dirigent_server.pagination import DEFAULT_PAGE, AfterParam, LimitParam, clip, uuid_cursor
from dirigent_server.security import OperatorDep, PrincipalDep
from dirigent_server.transactions import Transactional

router = APIRouter(route_class=Transactional, tags=["alerts"])


def render(rule: AlertRule, pipeline: str | None, connection: str | None = None) -> AlertRuleOut:
    """Render an alert rule, writing its throttle back as the humane duration it was."""
    return AlertRuleOut(
        id=rule.id,
        code=rule.code,
        name=rule.name,
        description=rule.description,
        event=rule.event,
        scope=rule.scope,
        pipeline=pipeline,
        notifier=rule.notifier,
        connection=connection,
        template=rule.template,
        throttle=format_duration(timedelta(seconds=rule.throttle_seconds)),
        active=rule.active,
        paused=rule.paused,
        last_sent_at=rule.last_sent_at,
        created_at=rule.created_at,
    )


@router.get(
    "/alert-rules",
    operation_id="listAlertRules",
    summary="List alert rules",
    response_model=Page[AlertRuleOut],
)
async def rules(
    session: SessionDep,
    principal: PrincipalDep,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[AlertRuleOut]:
    """List every alert rule, with the pipeline each one watches when it is scoped."""
    rows = await list_rules(session, after=uuid_cursor(after), limit=limit + 1)
    found = [
        render(rule, await _pipeline_code(session, rule), await _connection_code(session, rule.connection_id))
        for rule in rows
    ]
    items, following = clip(found, limit, lambda row: row.id)
    return Page(items=items, next=following)


@router.post(
    "/alert-rules",
    operation_id="createAlertRule",
    summary="Declare an alert rule",
    response_model=AlertRuleOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_rule(
    payload: AlertRuleIn, session: SessionDep, services: ServicesDep, principal: OperatorDep
) -> AlertRuleOut:
    """Declare an alert rule, refusing a notifier or a pipeline this instance does not have."""
    try:
        rule = await create_rule(
            session,
            services,
            AlertRuleRequest(
                code=payload.code,
                name=payload.name,
                description=payload.description,
                event=payload.event,
                notifier=payload.notifier,
                scope=payload.scope,
                pipeline=payload.pipeline,
                connection=payload.connection,
                template=payload.template,
                throttle=payload.throttle,
            ),
        )
    except AlertError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return render(rule, payload.pipeline, payload.connection)


@router.patch(
    "/alert-rules/{code}",
    operation_id="updateAlertRule",
    summary="Pause or resume an alert rule",
    response_model=AlertRuleOut,
)
async def change_rule(code: str, payload: AlertRuleUpdate, session: SessionDep, principal: OperatorDep) -> AlertRuleOut:
    """Hold a rule's deliveries, or let them resume.

    Pausing is instance state on the row rather than something the rule declares, so a rule an
    operator held keeps holding when the document that declared it is applied again.
    """
    rule = await _rule_or_404(session, code)
    await set_paused(session, rule, paused=payload.paused)
    return render(rule, await _pipeline_code(session, rule), await _connection_code(session, rule.connection_id))


@router.delete(
    "/alert-rules/{code}",
    operation_id="deleteAlertRule",
    summary="Delete an alert rule",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_rule(code: str, session: SessionDep, principal: OperatorDep) -> Response:
    """Remove an alert rule; the notifications it already raised are kept."""
    await delete_rule(session, await _rule_or_404(session, code))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/alert-rules/$test",
    operation_id="testNotifier",
    summary="Send a test message through a notifier",
    response_model=TestQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def test_notifier(
    payload: TestRequest, session: SessionDep, services: ServicesDep, principal: OperatorDep
) -> TestQueued:
    """Queue one message through a channel, on the same path a real alert takes."""
    try:
        notification = await queue_test_message(
            session,
            services,
            notifier=payload.notifier,
            connection=payload.connection,
            subject=payload.subject,
            body=payload.body,
        )
    except AlertError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return TestQueued(notification_id=notification.id, notifier=notification.notifier)


@router.get(
    "/notifications",
    operation_id="listNotifications",
    summary="List queued and delivered alerts",
    response_model=Page[NotificationOut],
)
async def notifications(
    session: SessionDep,
    services: ServicesDep,
    principal: PrincipalDep,
    run_id: Annotated[UUID | None, Query(description="Only this run's notifications.")] = None,
    notification_status: Annotated[
        NotificationStatus | None, Query(alias="status", description="Only rows in this state.")
    ] = None,
    notifier: Annotated[str | None, Query(description="Only rows this channel delivers.")] = None,
    after: AfterParam = None,
    limit: LimitParam = DEFAULT_PAGE,
) -> Page[NotificationOut]:
    """Read the alert queue, newest first."""
    rows = await list_notifications(
        session,
        run_id=run_id,
        notification_status=notification_status,
        notifier=notifier,
        after=uuid_cursor(after),
        limit=limit + 1,
    )
    found = [await _notification(session, services, row) for row in rows]
    items, following = clip(found, limit, lambda row: row.id)
    return Page(items=items, next=following)


@router.get(
    "/notifications/{notification_id}",
    operation_id="getNotification",
    summary="Read one queued or delivered alert",
    response_model=NotificationOut,
)
async def notification(
    notification_id: UUID, session: SessionDep, services: ServicesDep, principal: PrincipalDep
) -> NotificationOut:
    """Read one notification, which is how a caller watches a delivery it just queued."""
    return await _notification(session, services, await _notification_or_404(session, notification_id))


@router.post(
    "/notifications/{notification_id}/$retry",
    operation_id="retryNotification",
    summary="Put a notification back on the queue",
    response_model=NotificationOut,
)
async def retry(
    notification_id: UUID, session: SessionDep, services: ServicesDep, principal: OperatorDep
) -> NotificationOut:
    """Make one notification due now, so a worker takes it on its next pass."""
    row = await _notification_or_404(session, notification_id)
    try:
        await retry_notification(session, row)
    except AlertError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return await _notification(session, services, row)


async def _notification(session: SessionDep, services: ServicesDep, row: Notification) -> NotificationOut:
    """Render one notification row, naming the run by its pipeline rather than by its id."""
    run = await session.get(Run, row.run_id) if row.run_id else None
    pipeline = await session.get(Pipeline, run.pipeline_id) if run else None
    rule = await session.get(AlertRule, row.alert_rule_id) if row.alert_rule_id else None
    return NotificationOut(
        id=row.id,
        event=row.event,
        rule=rule.code if rule else None,
        notifier=row.notifier,
        connection=await _connection_code(session, row.connection_id),
        subject=row.subject,
        status=row.status,
        attempt=row.attempt,
        max_attempts=services.settings.notification_max_attempts,
        run_id=row.run_id,
        run_pipeline=pipeline.code if pipeline else None,
        run_started_at=run.started_at if run else None,
        available_at=row.available_at,
        sent_at=row.sent_at,
        error=row.error,
        created_at=row.created_at,
    )


async def _notification_or_404(session: SessionDep, notification_id: UUID) -> Notification:
    """Find one notification, or refuse with the id that named nothing."""
    row = await find_notification(session, notification_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no notification {notification_id}")
    return row


async def _rule_or_404(session: SessionDep, code: str) -> AlertRule:
    """Find one alert rule, or refuse with the code that named nothing."""
    rule = await find_rule(session, code)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"no alert rule coded {code!r}")
    return rule


async def _pipeline_code(session: SessionDep, rule: AlertRule) -> str | None:
    """Resolve the code of the pipeline a scoped rule watches."""
    if rule.pipeline_id is None:
        return None
    pipeline = await session.get(Pipeline, rule.pipeline_id)
    return pipeline.code if pipeline else None


async def _connection_code(session: SessionDep, connection_id: UUID | None) -> str | None:
    """Resolve the code of the connection a channel delivers through."""
    if connection_id is None:
        return None
    connection = await session.get(Connection, connection_id)
    return connection.code if connection else None
