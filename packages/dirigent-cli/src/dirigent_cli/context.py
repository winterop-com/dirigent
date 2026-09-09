"""The state every server-talking command shares: which server, and with what token."""

import logging
import os
from collections.abc import Awaitable
from functools import cached_property
from urllib.parse import urlsplit

import typer
from pydantic import BaseModel, ConfigDict

from dirigent_cli.output import (
    FULL_VERBOSITY,
    Detail,
    configure,
    refuse,
    write_refusal,
)
from dirigent_cli.profiles import Endpoint, ProfileError, resolve_endpoint
from dirigent_cli.stream import ansi
from dirigent_client import BlockingDirigent, DirigentError, TransportError
from dirigent_core.logging import NOISY_LOGGERS, configure_logging
from dirigent_core.protocol import Format

VERBOSITY: dict[int, str] = {0: "WARNING", 1: "INFO"}

LOG_LEVEL_ENV = "DIRIGENT_LOG_LEVEL"


class CliState(BaseModel):
    """The addressing flags, how loud to be, and the endpoint they resolve to."""

    model_config = ConfigDict(frozen=True, ignored_types=(cached_property,))

    url: str | None = None
    token: str | None = None
    profile: str | None = None
    verbose: int = 0
    debug: bool = False
    debug_all: bool = False
    output: Format = "json"

    chosen: bool = False
    """Whether a flag or the environment named the output, rather than it being the default.

    A command run once by a person -- ``dg init`` -- renders unless it was asked for records,
    and it can only tell the difference if the default is distinguishable from a choice.
    """

    @property
    def json_output(self) -> bool:
        """Report whether this invocation writes records rather than a rendering."""
        return self.output != "console"

    @property
    def detail(self) -> Detail:
        """Resolve how much this invocation emits, and how much of a value it shows.

        Verbosity decides it, and the output does not: the same flags produce the same
        records whether they are written as NDJSON or rendered, which is what makes
        ``dg run | dg format`` the same thing as ``dg run -o console``.
        """
        if self.debug or self.debug_all or self.verbose >= FULL_VERBOSITY:
            return Detail.FULL
        return Detail.VALUES if self.verbose else Detail.SUMMARY

    @property
    def level(self) -> str:
        """Resolve how loud to be: the flags first, then the environment, then quiet.

        ``--debug-all`` names a level as well as a cap: a flag that only lifted the caps
        would print nothing at all on its own.
        """
        if self.debug or self.debug_all:
            return "DEBUG"
        if self.verbose:
            return VERBOSITY.get(self.verbose, "DEBUG")
        return os.environ.get(LOG_LEVEL_ENV, VERBOSITY[0]).upper()

    @property
    def floors(self) -> dict[str, int]:
        """Cap the libraries whose debug output would drown dirigent's own."""
        if self.debug_all:
            return {}
        if self.level == "DEBUG":
            return dict.fromkeys(NOISY_LOGGERS, logging.WARNING)
        return dict(NOISY_LOGGERS)

    def configure_output(self) -> None:
        """Point process logging at the level this invocation asked for, and pick the medium."""
        configure(output=self.output, detail=self.detail)
        configure_logging(
            self.level,
            "console",
            floors=self.floors,
            cap_foreign=not self.debug_all,
            paint=ansi,
        )

    @cached_property
    def resolved(self) -> Endpoint:
        """Resolve the endpoint once: flags first, then DG_*, then the selected profile."""
        return self.endpoint()

    def endpoint(self, *, needs_token: bool = True) -> Endpoint:
        """Resolve the endpoint, refusing a profile without a token unless told not to."""
        try:
            return resolve_endpoint(url=self.url, token=self.token, profile=self.profile, needs_token=needs_token)
        except ProfileError as error:
            raise typer.BadParameter(str(error)) from error


def state_of(ctx: typer.Context) -> CliState:
    """Read the shared state off the Typer context, defaulting when there is none."""
    found = ctx.find_object(CliState)
    return found if found is not None else CliState()


#: What a refused connection to a loopback address adds: the local instance is not running.
LOCAL_INSTANCE_HINT = "nothing is listening there; uv run dg dev --keep-state in the project starts its instance"

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _is_local(url: str | None) -> bool:
    """Whether a URL addresses this machine, where a refused connection means nothing is running."""
    return bool(url) and (urlsplit(url or "").hostname or "") in LOOPBACK_HOSTS


class Session(BlockingDirigent):
    """The SDK, driven from the CLI's synchronous commands."""

    def call[T](self, awaitable: Awaitable[T]) -> T:
        """Run one API call, turning a refusal into a printed error and a non-zero exit."""
        try:
            return super().call(awaitable)
        except DirigentError as error:
            if error.problem is not None:
                write_refusal(error.problem)
            elif isinstance(error, TransportError) and _is_local(error.url):
                refuse(error.message, problems=[LOCAL_INSTANCE_HINT])
            else:
                refuse(error.message, status=error.status or 1)
            raise typer.Exit(code=1) from error


def client_for(state: CliState, *, needs_token: bool = True) -> Session:
    """Build the API client for a resolved endpoint."""
    endpoint = state.endpoint(needs_token=needs_token)
    return Session(url=endpoint.url, token=endpoint.token, api_prefix=endpoint.api_prefix)
