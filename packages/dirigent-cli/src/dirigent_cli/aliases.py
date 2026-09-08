"""Hidden aliases: ``ls`` for every ``list`` in the tree, and one for a single command."""

from typing import Final

import typer

LIST_COMMAND: Final = "list"
LIST_ALIAS: Final = "ls"


def add_list_aliases(app: typer.Typer, *, alias: str = LIST_ALIAS) -> list[str]:
    """Register a hidden ``ls`` beside every ``list`` in an app and its groups.

    Call after the whole tree is assembled; commands registered later are not walked.
    """
    aliased: list[str] = []
    for group in app.registered_groups:
        inner = group.typer_instance
        if inner is not None:
            aliased.extend(
                f"{group.name or inner.info.name or '?'} {name}" for name in add_list_aliases(inner, alias=alias)
            )
    if any(command.name == alias for command in app.registered_commands):
        return aliased
    for command in list(app.registered_commands):
        if command.name != LIST_COMMAND or command.callback is None:
            continue
        app.command(alias, hidden=True, help=command.help)(command.callback)
        aliased.append(alias)
    return aliased


def add_alias(app: typer.Typer, name: str, alias: str, *, hidden: bool = True) -> None:
    """Register a second name for one command, so muscle memory from another tool still lands."""
    for command in list(app.registered_commands):
        # A command registered without a name is named after its function, as typer does it.
        called = command.callback
        if called is not None and name in (command.name, called.__name__):
            app.command(alias, hidden=hidden, help=command.help)(called)
            return
    raise LookupError(f"no command named {name!r} to alias")
