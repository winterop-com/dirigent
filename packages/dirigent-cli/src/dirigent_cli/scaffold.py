"""Scaffolding for a new block pack: a package, one operator, a passing test."""

import re
from importlib.resources import files
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel

#: What a pack may be called: a lowercase identifier fragment, because it becomes half a
#: module name and an entry-point key.
NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*$")


class ScaffoldRecord(BaseModel):
    """One file the scaffold wrote."""

    kind: Literal["scaffold"] = "scaffold"
    path: str


class ScaffoldedRecord(BaseModel):
    """The closing record: where the pack is and what to run next."""

    kind: Literal["scaffolded"] = "scaffolded"
    directory: str
    next: list[str]


class ScaffoldError(Exception):
    """A scaffold that cannot proceed, with the reason as the message."""


def scaffold_pack(parent: Path, name: str) -> list[Path]:
    """Write a new pack under ``parent`` and answer with every file written.

    The directory is refused when it already exists, so running the command twice cannot
    half-overwrite somebody's edits.
    """
    if not NAME_PATTERN.match(name):
        raise ScaffoldError(f"{name!r} is not a pack name: lowercase letters, digits and _, starting with a letter")
    root = parent / f"dirigent-{name}"
    if root.exists():
        raise ScaffoldError(f"{root} already exists")
    title = name.replace("_", " ").title().replace(" ", "")
    module = root / "src" / f"dirigent_{name}"
    written = {
        root / "pyproject.toml": _template("pyproject.toml.tmpl", name=name, title=title),
        root / "README.md": _template("README.md.tmpl", name=name, title=title),
        module / "__init__.py": _template("__init__.py.tmpl", name=name, title=title),
        module / "py.typed": "",
        module / f"{name}.py": _template("operator.py.tmpl", name=name, title=title),
        root / "tests" / "test_plugin.py": _template("test_plugin.py.tmpl", name=name, title=title),
    }
    for path, text in written.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return list(written)


def _template(filename: str, **values: str) -> str:
    """Read one packaged template and fill its placeholders."""
    return (files("dirigent_cli") / "templates" / "pack" / filename).read_text().format(**values)
