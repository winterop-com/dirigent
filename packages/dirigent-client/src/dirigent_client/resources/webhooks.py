"""A pipeline's inbound webhooks: their mapping, their token, and what has arrived."""

from pydantic import SecretStr

from dirigent_client.enums import RunPriority
from dirigent_client.resources.base import Resource, query, request_body
from dirigent_client.schemas import DeliveryOut, Page, WebhookIn, WebhookOut, WebhookTokenOut


class Webhooks(Resource):
    """Declare, enable, rotate, and read the webhooks hanging from a pipeline."""

    async def list(self, pipeline: str, *, after: str | None = None, limit: int | None = None) -> Page[WebhookOut]:
        """List every webhook on a pipeline, with its mapping but never its token."""
        return await self._many(
            WebhookOut,
            "GET",
            f"/pipelines/{pipeline}/triggers/webhooks",
            params=query(after=after, limit=limit),
        )

    async def get(self, pipeline: str, code: str) -> WebhookOut:
        """Read one webhook by code, with its mapping but never its token."""
        return await self._one(WebhookOut, "GET", f"/pipelines/{pipeline}/triggers/webhooks/{code}")

    async def create(
        self,
        pipeline: str,
        code: str,
        *,
        name: str | None = None,
        description: str | None = None,
        params_from_payload: dict[str, str] | None = None,
        hmac_secret: str | None = None,
        rate_limit_per_minute: int = 60,
        priority: RunPriority | None = None,
    ) -> WebhookTokenOut:
        """Declare a webhook and return its token, which is shown here and nowhere else again."""
        payload = WebhookIn(
            code=code,
            name=name,
            description=description,
            params_from_payload=params_from_payload or {},
            hmac_secret=SecretStr(hmac_secret) if hmac_secret else None,
            rate_limit_per_minute=rate_limit_per_minute,
            priority=priority,
        )
        return await self._one(
            WebhookTokenOut,
            "POST",
            f"/pipelines/{pipeline}/triggers/webhooks",
            json=request_body(payload),
        )

    async def rotate_token(self, pipeline: str, code: str) -> WebhookTokenOut:
        """Mint a new token and forget the old one immediately; callers must be updated."""
        return await self._one(WebhookTokenOut, "POST", f"/pipelines/{pipeline}/triggers/webhooks/{code}/$rotate-token")

    async def enable(self, pipeline: str, code: str) -> WebhookOut:
        """Accept deliveries again on the token that was already issued."""
        return await self._one(WebhookOut, "POST", f"/pipelines/{pipeline}/triggers/webhooks/{code}/$enable")

    async def disable(self, pipeline: str, code: str) -> WebhookOut:
        """Refuse deliveries without rotating or losing the token."""
        return await self._one(WebhookOut, "POST", f"/pipelines/{pipeline}/triggers/webhooks/{code}/$disable")

    async def delete(self, pipeline: str, code: str) -> None:
        """Remove a webhook, its token, and its delivery history."""
        await self._transport.request("DELETE", f"/pipelines/{pipeline}/triggers/webhooks/{code}")

    async def deliveries(
        self, pipeline: str, code: str, *, after: str | None = None, limit: int | None = None
    ) -> Page[DeliveryOut]:
        """Read what has arrived, newest first, refusals included."""
        return await self._many(
            DeliveryOut,
            "GET",
            f"/pipelines/{pipeline}/triggers/webhooks/{code}/deliveries",
            params=query(after=after, limit=limit),
        )
