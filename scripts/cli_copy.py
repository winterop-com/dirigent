"""Print every sentence the CLI's help renders, as one reviewable inventory.

One line per surface: a command's summary, then each of its parameters' help. Reviewing
copy means reading this end to end, the same contract as scripts/ui_copy.py.
"""

import click
from typer.main import get_command

from dirigent_cli.main import app


def walk(command: click.Command, path: str) -> None:
    """Print one command's copy, then descend."""
    summary = (command.help or "").strip().splitlines()[0] if command.help else ""
    print(f"{path} :: {summary}")
    for parameter in command.params:
        if parameter.name in ("help",):
            continue
        text = (getattr(parameter, "help", None) or "").strip()
        if text:
            names = "/".join(parameter.opts)
            print(f"{path} {names} :: {text}")
    # Duck-typed rather than isinstance: typer's group classes do not always pass an
    # isinstance check against the click this script imported.
    if hasattr(command, "list_commands"):
        context = click.Context(command)
        for name in sorted(command.list_commands(context)):
            child = command.get_command(context, name)
            if child is not None:
                walk(child, f"{path} {name}")


def main() -> int:
    """Walk the whole tree from the root."""
    walk(get_command(app), "dg")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
