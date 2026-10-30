"""Profiles: which server the CLI talks to, how it gets a token for it, and how patient it is.

A profile is client-side only and must never hold a database URL: a CLI that could reach the
database would bypass authentication, attribution, and validation.

A project's file travels with its repository, so whoever wrote it may not be the person running
the CLI. It is read only when it is a regular file this user owns and nobody else may rewrite,
it can never name a command to run, and a credential from this user's shell does not follow a
URL it chose off this host. A project's ``.env`` is taken literally: a ``${VAR}`` in it is text.
"""

import io
import ipaddress
import os
import shutil
import stat
import subprocess
from collections.abc import Mapping
from datetime import timedelta
from pathlib import Path
from typing import Any, Final, cast
from urllib.parse import urlsplit

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from dirigent_cli.messages import PROFILE_NAMES_A_DATABASE
from dirigent_client import API_PREFIX, DEFAULT_CONNECT_TIMEOUT, DEFAULT_RETRIES, DEFAULT_TIMEOUT
from dirigent_common import Duration, EntityName

PROJECT_PROFILES: Final = Path(".dirigent") / "profiles.yaml"
PROJECT_ENV_FILE: Final = ".env"
USER_PROFILES: Final = Path.home() / ".config" / "dirigent" / "profiles.yaml"

URL_ENV: Final = "DG_URL"
TOKEN_ENV: Final = "DG_TOKEN"
PROFILE_ENV: Final = "DG_PROFILE"

DEFAULT_URL: Final = "http://127.0.0.1:3333"

DATABASE_SCHEMES: Final = ("postgresql", "postgres", "sqlite", "mysql")

TOKEN_COMMAND_TIMEOUT: Final = 30.0

DEFAULT_REQUEST_TIMEOUT: Final = timedelta(seconds=DEFAULT_TIMEOUT)
DEFAULT_CONNECT_BUDGET: Final = timedelta(seconds=DEFAULT_CONNECT_TIMEOUT)


class ProfileError(Exception):
    """A profile could not be read, found, or turned into a usable token."""


class Profile(BaseModel):
    """One named server, how to obtain a token for it, and how long to wait on it."""

    model_config = ConfigDict(frozen=True)

    name: str = "local"
    url: str = DEFAULT_URL
    token: SecretStr | None = None
    """An inline token, which is fine for a local dev server and nowhere else."""

    token_env: str | None = None
    token_cmd: str | None = None

    api_prefix: str = API_PREFIX
    """Where this instance serves its API, for one configured with a different prefix."""

    timeout: Duration = DEFAULT_REQUEST_TIMEOUT
    """How long a request to this instance may take to answer."""

    connect_timeout: Duration = DEFAULT_CONNECT_BUDGET
    """How long reaching this instance may take before it is called unreachable."""

    retries: int = Field(default=DEFAULT_RETRIES, ge=0)
    """How many further attempts a lost or refused-with-a-5xx request gets."""

    @model_validator(mode="after")
    def _refuse_a_database_url(self) -> "Profile":
        """Refuse a profile pointing at a database rather than at an API."""
        scheme = self.url.split("://", 1)[0].split("+", 1)[0].lower()
        if scheme in DATABASE_SCHEMES:
            raise ValueError(PROFILE_NAMES_A_DATABASE.render(name=repr(self.name)))
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

    @property
    def is_project(self) -> bool:
        """Whether this file belongs to a project rather than to the user."""
        return self.path is not None and _is_project(self.path)

    @property
    def env_file(self) -> Path | None:
        """The ``.env`` at the root of the project this file belongs to, or none for the user file."""
        if self.path is None or not self.is_project:
            return None
        return self.path.parent.parent / PROJECT_ENV_FILE

    def environment(self, environ: Mapping[str, str]) -> dict[str, str]:
        """The environment a profile resolves in: the process's, with the project's ``.env`` filling gaps."""
        path = self.env_file
        text = None if path is None else _read_project_file(path)
        if text is None:
            return dict(environ)
        parsed = dotenv_values(stream=io.StringIO(text), interpolate=False)
        from_file = {key: value for key, value in parsed.items() if value is not None}
        return {**from_file, **environ}

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


def _is_project(path: Path) -> bool:
    """Whether a profiles file sits in a project's ``.dirigent`` directory."""
    return path.parent.name == PROJECT_PROFILES.parent.name


def _read_project_file(path: Path) -> str | None:
    """Read a project's file, or answer none unless it may be trusted as the project's own.

    Neither the file nor its directory may be a symbolic link, and the file must be a regular
    one this user owns that neither group nor others may write. Every check is made on the
    opened descriptor, so the file read is the file checked.
    """
    try:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        finally:
            os.close(directory)
        with os.fdopen(descriptor, encoding="utf-8") as opened:
            status = os.fstat(opened.fileno())
            if not stat.S_ISREG(status.st_mode):
                return None
            if status.st_uid != os.getuid() or status.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return None
            return opened.read()
    except (OSError, UnicodeDecodeError):
        return None


def _is_loopback(url: str) -> bool:
    """Whether a URL names this host, so a token sent to it does not leave the machine."""
    host = urlsplit(url).hostname
    if host is None or "\\" in url:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def candidate_paths(start: Path | None = None) -> list[Path]:
    """List the profiles files that apply here, most specific first."""
    here = (start or Path.cwd()).resolve()
    found = [directory / PROJECT_PROFILES for directory in [here, *here.parents]]
    return [*found, USER_PROFILES]


def load_store(path: Path) -> ProfileStore:
    """Read one profiles file, naming the profile in every error it raises."""
    try:
        text = path.read_text()
    except OSError as error:
        raise ProfileError(f"{path} could not be read: {error}") from error
    return _parse_store(path, text)


def _parse_store(path: Path, text: str) -> ProfileStore:
    """Turn a profiles file's text into a store, naming the profile in every error it raises."""
    try:
        loaded: object = yaml.safe_load(text)
    except yaml.YAMLError as error:
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
            if _is_project(path) and cast("dict[str, Any]", body).get("token_cmd"):
                raise ProfileError(
                    f"{path}: profile {name!r} sets token_cmd, and a project's file may not name a command "
                    f"to run; move this profile to {USER_PROFILES}"
                )
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
    """Read the first profiles file that exists and may be read, or an empty store when none does.

    A project's file that ``_read_project_file`` refuses is passed over, as though it were not
    there.
    """
    for path in candidate_paths(start):
        if not _is_project(path):
            if path.is_file():
                return load_store(path)
            continue
        text = _read_project_file(path)
        if text is not None:
            return _parse_store(path, text)
    return ProfileStore()


class Endpoint(BaseModel):
    """The resolved answer to "which server, with what token"."""

    model_config = ConfigDict(frozen=True)

    url: str
    token: str | None = None
    profile: str | None = None
    source: str = "default"
    api_prefix: str = API_PREFIX
    timeout: Duration = DEFAULT_REQUEST_TIMEOUT
    connect_timeout: Duration = DEFAULT_CONNECT_BUDGET
    retries: int = DEFAULT_RETRIES


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

    A project's ``.env`` stands in for any ``DG_*`` variable the environment does not set.
    With ``needs_token`` off, a profile whose token cannot be resolved yields no token rather
    than refusing, which is what the command that mints one asks for.

    A token the project did not supply itself, through its file or its ``.env``, is refused on
    its way to a URL the project chose, unless that URL is on this host.
    """
    shell = environ if environ is not None else os.environ
    store = find_store(start)
    env = store.environment(shell)
    chosen = store.select(profile or env.get(PROFILE_ENV))

    url_from_project = False
    if url is not None:
        source = "flag"
    elif env.get(URL_ENV):
        source, url = "environment", env[URL_ENV]
        url_from_project = not shell.get(URL_ENV)
    elif chosen is not None:
        source, url = f"profile {chosen.name}", chosen.url
        url_from_project = store.is_project
    else:
        source, url = "default", DEFAULT_URL

    resolved_token = token or env.get(TOKEN_ENV) or None
    token_from_shell = bool(token or shell.get(TOKEN_ENV))
    if resolved_token is None and chosen is not None:
        token_from_shell = bool(chosen.token is None and chosen.token_env and shell.get(chosen.token_env))
        try:
            resolved_token = chosen.resolve_token(env)
        except ProfileError:
            if needs_token:
                raise
    if resolved_token is not None and token_from_shell and url_from_project and not _is_loopback(url):
        if needs_token:
            raise ProfileError(
                f"{store.path} names {url}, and the token in this shell was not issued for a project to "
                f"send where it likes; name the server yourself with --url or {URL_ENV}, or keep a token "
                f"for it in {store.env_file}"
            )
        resolved_token = None
    return Endpoint(
        url=url.rstrip("/"),
        token=resolved_token,
        profile=chosen.name if chosen else None,
        source=source,
        api_prefix=chosen.api_prefix if chosen else API_PREFIX,
        timeout=chosen.timeout if chosen else DEFAULT_REQUEST_TIMEOUT,
        connect_timeout=chosen.connect_timeout if chosen else DEFAULT_CONNECT_BUDGET,
        retries=chosen.retries if chosen else DEFAULT_RETRIES,
    )
