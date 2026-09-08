"""The pydantic types more than one package has to agree on.

A block's config and output are published as JSON Schema, so their base makes a field's
docstring its description. The HTTP connection is here rather than in the standard library
so an adapter pack presents the same one, instead of redefining base URL, auth, TLS and
timeouts into a fourth slightly different form.
"""

from datetime import timedelta

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from dirigent_common.durations import Duration


class BlockModel(BaseModel):
    """The base every block's config and output model should use.

    Each field's docstring becomes its description in the published JSON Schema, and an
    unknown key is refused rather than ignored -- which also publishes the schema with
    ``additionalProperties: false``, so a document is refused at apply and not at the run.
    """

    model_config = ConfigDict(use_attribute_docstrings=True, extra="forbid")


class HealthReport(BaseModel):
    """The outcome of checking a connection against its external system."""

    healthy: bool
    detail: str | None = None
    version: str | None = None


class HttpConnectionConfig(BlockModel):
    """Everything needed to talk to one HTTP service, credentials included."""

    base_url: str = Field(min_length=1)
    """The service root every request path is resolved against."""

    bearer_token: SecretStr | None = None
    """A bearer credential, sent as an Authorization header."""

    basic_username: str | None = None
    """The user half of HTTP basic authentication."""

    basic_password: SecretStr | None = None
    """The secret half of HTTP basic authentication."""

    hmac_secret: SecretStr | None = None
    """A shared secret an outbound POST is signed with, mirroring an inbound webhook's.

    It lives on the connection rather than in a document for the same reason every other
    credential does: a document is portable and a secret is not. It is not sent as a header
    and never authenticates a request on its own -- ``webhook.post`` uses it to sign the
    exact bytes it puts on the wire."""

    verify_tls: bool = True
    """Whether certificates are verified; turning this off is a per-connection decision."""

    timeout: Duration = Field(default=timedelta(seconds=30), gt=timedelta(0))
    """The timeout applied to every request through this connection."""

    health_path: str = "/"
    """What a connection check requests to decide whether the service is reachable."""
