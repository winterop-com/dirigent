"""The profile command group: which profiles apply here, which one is selected, and how it resolves.

Nothing here prints a token. A profile is described by how its token is obtained, and
``dg profile show`` says only whether one is available now.
"""

import os
from pathlib import Path
from typing import Annotated, Literal, NoReturn

import typer
from pydantic import BaseModel

from dirigent_cli import profiles
from dirigent_cli.context import state_of
from dirigent_cli.messages import PROFILE_NOT_HERE, PROFILE_REFUSED
from dirigent_cli.output import emit_one, emit_records, printable, refuse
from dirigent_cli.profiles import (
    PROFILE_ENV,
    TOKEN_ENV,
    URL_ENV,
    Profile,
    ProfileError,
    ProfileStore,
    find_store,
    load_store,
)
from dirigent_common import Duration, Message

profile_app = typer.Typer(
    name="profile",
    help="The profiles that apply here: which servers, which one is selected, and how each gets its token.",
    no_args_is_help=True,
)

Scope = Literal["project", "user"]


class ProfileRow(BaseModel):
    """One profile as a listing shows it: where it is declared, whether it is chosen, how it gets a token."""

    name: str
    url: str
    file: str
    scope: Scope
    default: bool
    """Whether its file names it as the default."""

    selected: bool
    """Whether a command run here with no ``--profile`` would use it."""

    active: bool
    """Whether its file is the one commands run here read; a user profile beside a project file is not."""

    token: str | None
    """How its token is obtained: ``token``, ``token_env NAME`` or ``token_cmd``, or none."""


class ResolvedProfile(ProfileRow):
    """One profile resolved for a command run here, without its token."""

    selected_by: str
    """What chose it: the argument, ``--profile``, ``DG_PROFILE``, the file's default, or being the only one."""

    api_prefix: str
    timeout: Duration
    connect_timeout: Duration
    retries: int
    token_available: bool
    """Whether a token can be obtained now, by ``DG_TOKEN`` or by the profile's own mechanism."""

    token_problem: str | None = None
    """Why none can, when none can."""

    overridden_by: list[str]
    """The variables set here that win over this profile's URL or token, such as ``DG_URL``."""


def token_source(profile: Profile) -> str | None:
    """Say how a profile obtains its token, never what the token is."""
    if profile.token is not None:
        return "token"
    if profile.token_env:
        return f"token_env {profile.token_env}"
    if profile.token_cmd:
        return "token_cmd"
    return None


def _stores() -> tuple[ProfileStore, list[ProfileStore]]:
    """The store commands here read, and every store that applies here, project first."""
    active = find_store()
    stores = [active] if active.path is not None else []
    user = profiles.USER_PROFILES
    if active.path != user and user.is_file():
        stores.append(load_store(user))
    return active, stores


def _selection(active: ProfileStore, asked: str | None) -> tuple[str | None, str]:
    """Name the profile a command run here uses, and what chose it."""
    environment = active.environment(os.environ)
    if asked:
        return asked, "--profile"
    if environment.get(PROFILE_ENV):
        return environment[PROFILE_ENV], PROFILE_ENV
    if active.default:
        return active.default, "default"
    if len(active.profiles) == 1:
        return next(iter(active.profiles)), "only profile"
    return None, "none"


def _row(store: ProfileStore, profile: Profile, *, active: ProfileStore, selected: str | None) -> ProfileRow:
    """Describe one profile of one store."""
    in_use = store.path == active.path
    return ProfileRow(
        name=profile.name,
        url=profile.url,
        file=str(store.path),
        scope="project" if store.is_project else "user",
        default=store.default == profile.name,
        selected=in_use and selected == profile.name,
        active=in_use,
        token=token_source(profile),
    )


def _refuse(message: Message, detail: str) -> NoReturn:
    """Refuse with a profile's own explanation, and end the command."""
    refuse(message, status=2, detail=printable(detail))
    raise typer.Exit(code=2)


def _active_store() -> ProfileStore:
    """Read the store commands here read, refusing one that cannot be read."""
    try:
        return find_store()
    except ProfileError as error:
        _refuse(PROFILE_REFUSED, str(error))


@profile_app.command("list")
def profile_list(ctx: typer.Context) -> None:
    """List every profile from the project's file and the user's, and which one is selected here."""
    try:
        active, stores = _stores()
    except ProfileError as error:
        _refuse(PROFILE_REFUSED, str(error))
    selected, _ = _selection(active, state_of(ctx).profile)
    rows = [
        _row(store, profile, active=active, selected=selected)
        for store in stores
        for profile in store.profiles.values()
    ]
    emit_records("profile", rows)


@profile_app.command("show")
def profile_show(
    ctx: typer.Context,
    name: Annotated[str | None, typer.Argument(help="The profile to show; the one selected here when omitted.")] = None,
) -> None:
    """Show one profile resolved: its URL, API prefix, timeouts, and whether a token is available now."""
    active = _active_store()
    chosen, by = (name, "argument") if name else _selection(active, state_of(ctx).profile)
    if chosen is None:
        _refuse(
            PROFILE_NOT_HERE,
            f"no profile is selected here: {active.path or 'no profiles file applies'}; name one, pass --profile, "
            f"set {PROFILE_ENV}, or give the file a default",
        )
    profile = active.profiles.get(chosen)
    if profile is None:
        _refuse(PROFILE_NOT_HERE, _missing(active, chosen))
    environment = active.environment(os.environ)
    available, problem = _token_available(profile, environment)
    row = _row(active, profile, active=active, selected=_selection(active, state_of(ctx).profile)[0])
    emit_one(
        "profile",
        ResolvedProfile(
            **row.model_dump(),
            selected_by=by,
            api_prefix=profile.api_prefix,
            timeout=profile.timeout,
            connect_timeout=profile.connect_timeout,
            retries=profile.retries,
            token_available=available,
            token_problem=problem,
            overridden_by=[variable for variable in (URL_ENV, TOKEN_ENV) if environment.get(variable)],
        ),
    )


def _missing(active: ProfileStore, wanted: str) -> str:
    """Say why a named profile is not one commands here can use."""
    user = profiles.USER_PROFILES
    if active.path != user and user.is_file():
        try:
            elsewhere = load_store(user)
        except ProfileError:
            elsewhere = None
        if elsewhere is not None and wanted in elsewhere.profiles:
            return f"profile {wanted!r} is in {user}, and commands here read {active.path}, which does not declare it"
    known = ", ".join(sorted(active.profiles)) or "it declares none"
    where = active.path or Path("no profiles file")
    return f"no profile named {wanted!r} in {where} ({known})"


def _token_available(profile: Profile, environment: dict[str, str]) -> tuple[bool, str | None]:
    """Say whether a token can be had now, without keeping it."""
    if environment.get(TOKEN_ENV):
        return True, None
    try:
        token = profile.resolve_token(environment)
    except ProfileError as error:
        return False, str(error)
    if token is None:
        return False, f"profile {profile.name!r} names no token, and {TOKEN_ENV} is not set"
    return True, None
