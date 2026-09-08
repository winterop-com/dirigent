"""Profiles: which server the CLI talks to, and how it gets a token for it.

A profile is client-side addressing only and must never hold a database URL: a CLI that
could reach the database would bypass authentication, attribution, and validation.
"""

import os
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from dirigent_client import API_PREFIX
from dirigent_common import EntityName

PROJECT_PROFILES: Final = Path(".dirigent") / "profiles.yaml"
USER_PROFILES: Final = Path.home() / ".config" / "dirigent" / "profiles.yaml"

URL_ENV: Final = "DG_URL"
TOKEN_ENV: Final = "DG_TOKEN"
PROFILE_ENV: Final = "DG_PROFILE"

DEFAULT_URL: Final = "http://127.0.0.1:3333"

DATABASE_SCHEMES: Final = ("postgresql", "postgres", "sqlite", "mysql")

TOKEN_COMMAND_TIMEOUT: Final = 30.0


class ProfileError(Exception):
    """A profile could not be read, found, or turned into a usable token."""


class Profile(BaseModel):
    """One named server and how to obtain a token for it."""

    model_config = ConfigDict(frozen=True)

    name: str = "local"
    url: str = DEFAULT_URL
    token: SecretStr | None = None
    """An inline token, which is fine for a local dev server and nowhere else."""

    token_env: str | None = None
    token_cmd: str | None = None

    api_prefix: str = API_PREFIX
    """Where this instance serves its API, for one configured with a different prefix."""

    @model_validator(mode="after")
    def _refuse_a_database_url(self) -> "Profile":
        """Refuse a profile pointing at a database rather than at an API."""
        scheme = self.url.split("://", 1)[0].split("+", 1)[0].lower()
        if scheme in DATABASE_SCHEMES:
            raise ValueError(
                f"profile {self.name!r} names a database URL. Profiles address a server over HTTP; "
                f"a database URL belongs in DIRIGENT_DATABASE_URL on the host that runs it"
            )
        return self

    def resolve_token(self, environ: Mapping[str, str] | None = None) -> str | None:
        """Obtain the token this profile describes, by whichever of the three mechanisms it uses."""
        if self.token is not None:
            return self.token.get_secret_value()
        if self.token_env:
            value = (environ if environ is not None else os.environ).get(self.token_env)
            if not value:
                raise ProfileError(f"profile {self.name!r} reads its token from ${self.token_env}, which is not set")
            return value
        if self.token_cmd:
            return self._run_token_command()
        return None

    def _run_token_command(self) -> str:
        """Run the command that prints the token, and refuse anything that is not a token."""
        command = self.token_cmd or ""
        argv = command.split()
        if not argv or shutil.which(argv[0]) is None:
            raise ProfileError(f"profile {self.name!r} runs {command!r} for its token, which is not on PATH")
        try:
            finished = subprocess.run(  # noqa: S603 - the command is the operator's own configuration
                argv,
                capture_output=True,
                text=True,
                timeout=TOKEN_COMMAND_TIMEOUT,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise ProfileError(f"profile {self.name!r}: {command!r} did not finish in time") from error
        if finished.returncode != 0:
            detail = finished.stderr.strip() or f"exit code {finished.returncode}"
            raise ProfileError(f"profile {self.name!r}: {command!r} failed ({detail})")
        token = finished.stdout.strip()
        if not token:
            raise ProfileError(f"profile {self.name!r}: {command!r} printed nothing")
        return token


class ProfileStore(BaseModel):
    """A profiles file: the named servers, and which one is used when none is asked for."""

    model_config = ConfigDict(frozen=True)

    default: str | None = None
    profiles: dict[EntityName, Profile] = Field(default_factory=dict[str, Profile])
    path: Path | None = None

    def select(self, name: str | None) -> Profile | None:
        """Choose a profile by name, by the file's default, or by there being only one."""
        wanted = name or self.default
        if wanted is None:
            return next(iter(self.profiles.values())) if len(self.profiles) == 1 else None
        found = self.profiles.get(wanted)
        if found is None:
            known = ", ".join(sorted(self.profiles)) or "this file defines none"
            where = f" in {self.path}" if self.path else ""
            raise ProfileError(f"no profile named {wanted!r}{where} ({known})")
        return found


def candidate_paths(start: Path | None = None) -> list[Path]:
    """List the profiles files that apply here, most specific first."""
    here = (start or Path.cwd()).resolve()
    found = [directory / PROJECT_PROFILES for directory in [here, *here.parents]]
    return [*found, USER_PROFILES]


def load_store(path: Path) -> ProfileStore:
    """Read one profiles file, naming the profile in every error it raises."""
    try:
        loaded: object = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise ProfileError(f"{path} could not be read: {error}") from error
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ProfileError(f"{path} should hold a mapping with 'default' and 'profiles' keys")
    raw = cast("dict[str, Any]", loaded)
    declared = raw.get("profiles")
    profiles: dict[str, Profile] = {}
    if isinstance(declared, dict):
        for name, body in cast("dict[str, Any]", declared).items():
            if not isinstance(body, dict):
                raise ProfileError(f"{path}: profile {name!r} is not a mapping")
            try:
                profiles[name] = Profile(name=name, **cast("dict[str, Any]", body))
            except ValueError as error:
                raise ProfileError(f"{path}: {error}") from error
    default = raw.get("default")
    return ProfileStore(
        default=default if isinstance(default, str) else None,
        profiles=profiles,
        path=path,
    )


def find_store(start: Path | None = None) -> ProfileStore:
    """Read the first profiles file that exists, or an empty store when none does."""
    for path in candidate_paths(start):
        if path.is_file():
            return load_store(path)
    return ProfileStore()


class Endpoint(BaseModel):
    """The resolved answer to "which server, with what token"."""

    model_config = ConfigDict(frozen=True)

    url: str
    token: str | None = None
    profile: str | None = None
    source: str = "default"
    api_prefix: str = API_PREFIX


def resolve_endpoint(
    *,
    url: str | None = None,
    token: str | None = None,
    profile: str | None = None,
    start: Path | None = None,
    environ: dict[str, str] | None = None,
    needs_token: bool = True,
) -> Endpoint:
    """Resolve the server and token: flags first, then ``DG_*``, then the selected profile.

    With ``needs_token`` off, a profile whose token cannot be resolved yields no token rather
    than refusing, which is what the command that mints one asks for.
    """
    env = environ if environ is not None else dict(os.environ)
    store = find_store(start)
    chosen = store.select(profile or env.get(PROFILE_ENV))

    if url is not None:
        source = "flag"
    elif env.get(URL_ENV):
        source, url = "environment", env[URL_ENV]
    elif chosen is not None:
        source, url = f"profile {chosen.name}", chosen.url
    else:
        source, url = "default", DEFAULT_URL

    resolved_token = token or env.get(TOKEN_ENV) or None
    if resolved_token is None and chosen is not None:
        try:
            resolved_token = chosen.resolve_token(env)
        except ProfileError:
            if needs_token:
                raise
    return Endpoint(
        url=url.rstrip("/"),
        token=resolved_token,
        profile=chosen.name if chosen else None,
        source=source,
        api_prefix=chosen.api_prefix if chosen else API_PREFIX,
    )
