"""Alert rules, and the notification queue they deliver through."""

from datetime import timedelta
from uuid import UUID

from dirigent_client.enums import AlertEvent, AlertScope
from dirigent_client.resources.base import Resource, query, request_body
from dirigent_client.schemas import (
    AlertRuleIn,
    AlertRuleOut,
    AlertRuleUpdate,
    NotificationOut,
    Page,
    TestQueued,
    TestRequest,
)
from dirigent_common import to_timedelta


class Alerts(Resource):
    """Declare and remove alert rules, send a test message, and read the queue."""

    async def rules(self, *, after: str | None = None, limit: int | None = None) -> Page[AlertRuleOut]:
        """List every alert rule, with the pipeline each one watches when it is scoped."""
        return await self._many(AlertRuleOut, "GET", "/alert-rules", params=query(after=after, limit=limit))

    async def create_rule(
        self,
        code: str,
        *,
        name: str | None = None,
        description: str | None = None,
        event: AlertEvent,
        notifier: str,
        scope: AlertScope = AlertScope.GLOBAL,
        pipeline: str | None = None,
        connection: str | None = None,
        template: str | None = None,
        body: str | None = None,
        throttle: timedelta | str = timedelta(0),
    ) -> AlertRuleOut:
        """Declare an alert rule, refusing a notifier or a pipeline this instance does not have."""
        payload = AlertRuleIn(
            code=code,
            name=name,
            description=description,
            event=event,
            notifier=notifier,
            scope=scope,
            pipeline=pipeline,
            connection=connection,
            template=template,
            body=body,
            throttle=to_timedelta(throttle),
        )
        return await self._one(AlertRuleOut, "POST", "/alert-rules", json=request_body(payload))

    async def set_rule_paused(self, code: str, *, paused: bool) -> AlertRuleOut:
        """Hold a rule's deliveries, or let them resume."""
        return await self.update_rule(code, paused=paused)

    async def update_rule(
        self,
        code: str,
        *,
        paused: bool | None = None,
        template: str | None = None,
        body: str | None = None,
    ) -> AlertRuleOut:
        """Change what a rule says or whether it delivers.

        A field this call was not given is absent from the body, which is how the endpoint
        tells "leave it alone" from "clear it".
        """
        named = query(paused=paused, template=template, body=body)
        body_json = AlertRuleUpdate.model_validate(named).model_dump(mode="json", exclude_unset=True)
        return await self._one(AlertRuleOut, "PATCH", f"/alert-rules/{code}", json=body_json)

    async def delete_rule(self, code: str) -> None:
        """Remove an alert rule; the notifications it already raised are kept."""
        await self._transport.request("DELETE", f"/alert-rules/{code}")

    async def test(
        self,
        *,
        notifier: str,
        connection: str | None = None,
        subject: str | None = None,
        body: str | None = None,
    ) -> TestQueued:
        """Queue one message through a channel, on the same path a real alert takes."""
        declared = TestRequest(notifier=notifier, connection=connection)
        payload = declared.model_copy(
            update=query(subject=subject, body=body),
        )
        return await self._one(TestQueued, "POST", "/alert-rules/$test", json=request_body(payload))

    async def notification(self, notification_id: UUID | str) -> NotificationOut:
        """Read one notification, which is how a caller watches a delivery it just queued."""
        return await self._one(NotificationOut, "GET", f"/notifications/{notification_id}")

    async def retry(self, notification_id: UUID | str) -> NotificationOut:
        """Put one notification back on the queue, due now."""
        return await self._one(NotificationOut, "POST", f"/notifications/{notification_id}/$retry")

    async def notifications(
        self, *, run_id: UUID | str | None = None, after: str | None = None, limit: int | None = None
    ) -> Page[NotificationOut]:
        """Read the alert queue newest first, which is where an undelivered alert is visible."""
        return await self._many(
            NotificationOut,
            "GET",
            "/notifications",
            params=query(run_id=str(run_id) if run_id else None, after=after, limit=limit),
        )
