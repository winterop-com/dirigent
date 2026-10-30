"""A pipeline's sources: what each listens to, its state, what has arrived, and its token."""

from pydantic import SecretStr

from dirigent_client.resources.base import Resource, query, segment
from dirigent_client.schemas import Page, SetSecretRequest, SourceInputOut, SourceOut, SourceTokenOut


class Sources(Resource):
    """Read, pause, resume and rotate the sources a pipeline's document declares."""

    async def list(
        self, pipeline: str | None = None, *, after: str | None = None, limit: int | None = None
    ) -> Page[SourceOut]:
        """List one pipeline's sources, or every pipeline's, never their tokens."""
        path = f"/pipelines/{segment(pipeline)}/sources" if pipeline is not None else "/sources"
        return await self._many(SourceOut, "GET", path, params=query(after=after, limit=limit))

    async def get(self, pipeline: str, code: str) -> SourceOut:
        """Read one source by its step code, never its token."""
        return await self._one(SourceOut, "GET", f"/pipelines/{segment(pipeline)}/sources/{segment(code)}")

    async def pause(self, pipeline: str, code: str) -> SourceOut:
        """Refuse new inputs with 503, keeping the token and the counts."""
        return await self._one(SourceOut, "POST", f"/pipelines/{segment(pipeline)}/sources/{segment(code)}/$pause")

    async def resume(self, pipeline: str, code: str) -> SourceOut:
        """Take inputs again on the token that was already issued."""
        return await self._one(SourceOut, "POST", f"/pipelines/{segment(pipeline)}/sources/{segment(code)}/$resume")

    async def rotate_token(self, pipeline: str, code: str) -> SourceTokenOut:
        """Mint a new token or signing secret and forget the old one immediately; every caller has to be given it."""
        return await self._one(
            SourceTokenOut, "POST", f"/pipelines/{segment(pipeline)}/sources/{segment(code)}/$rotate-token"
        )

    async def set_secret(self, pipeline: str, code: str, secret: str) -> SourceOut:
        """Replace a signed source's signing secret with one its sender issued."""
        body = SetSecretRequest(secret=SecretStr(secret))
        return await self._one(
            SourceOut,
            "POST",
            f"/pipelines/{segment(pipeline)}/sources/{segment(code)}/$set-secret",
            json={"secret": body.secret.get_secret_value()},
        )

    async def inputs(
        self, pipeline: str, code: str, *, after: str | None = None, limit: int | None = None
    ) -> Page[SourceInputOut]:
        """Read what has arrived, newest first, refusals included."""
        return await self._many(
            SourceInputOut,
            "GET",
            f"/pipelines/{segment(pipeline)}/sources/{segment(code)}/inputs",
            params=query(after=after, limit=limit),
        )
