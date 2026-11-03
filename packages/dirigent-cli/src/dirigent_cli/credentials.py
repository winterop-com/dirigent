"""Choosing how a new connection authenticates, where its kind takes one of several credentials."""

from collections.abc import Mapping
from typing import Any, Final, cast

import typer

from dirigent_cli.messages import CONNECTION_NEEDS_A_CREDENTIAL, CREDENTIAL_FORM
from dirigent_cli.output import refuse
from dirigent_client.schemas import SurfaceEntry
from dirigent_common import CredentialForm, Issue

#: What the choice between a kind's credential forms is asked as.
CHOICE_LABEL: Final = "authenticate with"

#: The answer that leaves a kind whose credential is optional without one.
NO_CREDENTIAL: Final = "none"


def credential_fields(entry: SurfaceEntry) -> frozenset[str]:
    """Every config field one of the kind's credential forms sets."""
    return frozenset(field for form in entry.credential_forms for field in form.fields)


def is_secret_field(body: Mapping[str, Any]) -> bool:
    """Report whether a schema field is one the server will redact.

    ``format: password`` is the same declaration that makes the engine encrypt the field, so
    hiding the prompt and encrypting the value stay in agreement.
    """
    if body.get("format") == "password":
        return True
    options = cast("list[object]", body.get("anyOf") or [])
    return any(
        isinstance(option, dict) and cast("dict[str, Any]", option).get("format") == "password" for option in options
    )


def set_flags(form: CredentialForm) -> str:
    """The ``--set`` flags that give one form on the command line."""
    return " ".join(f"--set {field}=..." for field in form.fields)


def choose_a_credential(
    entry: SurfaceEntry,
    config: dict[str, Any],
    properties: Mapping[str, Any],
    *,
    interactive: bool,
    offered: bool,
) -> None:
    """Fill in the credential a connection authenticates with, or refuse one that has none.

    A form the invocation already started is completed. At a terminal with none started the
    person picks one, where the kind needs one or ``offered`` says the command is the form.
    Outside a terminal a kind that needs a credential and got none is refused with every form
    and the flags that give it.
    """
    forms = entry.credential_forms
    if not forms:
        return
    started = [form for form in forms if any(field in config for field in form.fields)]
    if not interactive:
        if not started and entry.credential_required:
            refuse(
                CONNECTION_NEEDS_A_CREDENTIAL,
                title="No credential",
                problems=[Issue.of(CREDENTIAL_FORM, form=form.code, flags=set_flags(form)) for form in forms],
                kind=entry.id,
                forms=" or ".join(form.code for form in forms),
            )
            raise typer.Exit(code=1)
        return
    if not started and not (offered or entry.credential_required):
        return
    chosen = started or [form for form in [_pick(entry)] if form is not None]
    for form in chosen:
        for field in form.fields:
            if field in config:
                continue
            body = cast("Mapping[str, Any]", properties.get(field) or {})
            config[field] = typer.prompt(field, hide_input=True) if is_secret_field(body) else typer.prompt(field)


def _pick(entry: SurfaceEntry) -> CredentialForm | None:
    """Ask which form to authenticate with, offering none where the kind may go without."""
    codes = [form.code for form in entry.credential_forms]
    if not entry.credential_required:
        codes.append(NO_CREDENTIAL)

    def one_of(answer: str) -> str:
        if answer not in codes:
            raise typer.BadParameter(f"{answer!r} is not one of {', '.join(codes)}")
        return answer

    answer = str(
        typer.prompt(
            choice_label(entry),
            default=codes[0] if entry.credential_required else NO_CREDENTIAL,
            value_proc=one_of,
        )
    )
    return next((form for form in entry.credential_forms if form.code == answer), None)


def choice_label(entry: SurfaceEntry) -> str:
    """The question the choice of form is asked as, naming every answer it takes."""
    codes = [form.code for form in entry.credential_forms]
    if not entry.credential_required:
        codes.append(NO_CREDENTIAL)
    return f"{CHOICE_LABEL} ({', '.join(codes)})"
