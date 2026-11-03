"""The dirigent-cli version a project pins, and whether the running ``dg`` is one it allows.

A project's ``pyproject.toml`` names the runtime it was written for, and ``uv run dg`` is that
runtime. A ``dg`` from elsewhere on the path -- a ``uv tool`` install, an old virtualenv -- reads
and writes the same ``.dirigent/state`` and the same instance.
"""

import tomllib
from pathlib import Path
from typing import Any, Final, cast

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict

#: Set to 1, this runs a ``dg`` the project does not pin anyway.
ALLOW_ENV: Final = "DG_ALLOW_VERSION_MISMATCH"

DISTRIBUTION: Final = canonicalize_name("dirigent-cli")


class Pin(BaseModel):
    """What one project's ``pyproject.toml`` says about dirigent-cli."""

    model_config = ConfigDict(frozen=True)

    project: Path
    """The directory holding the ``pyproject.toml``."""

    specifier: str
    """The version specifier as written, such as ``==0.32.0`` or ``>=0.32,<0.33``."""

    def allows(self, running: str) -> bool:
        """Whether a version satisfies the pin; one that is not a version never does."""
        try:
            return SpecifierSet(self.specifier).contains(Version(running), prereleases=True)
        except InvalidVersion:
            return False


def _requirements(document: dict[str, Any]) -> list[str]:
    """Every requirement string the project and its dependency groups list."""
    project = document.get("project")
    found: list[str] = []
    if isinstance(project, dict):
        listed = cast("dict[str, Any]", project).get("dependencies")
        if isinstance(listed, list):
            found.extend(item for item in cast("list[object]", listed) if isinstance(item, str))
    groups = document.get("dependency-groups")
    if isinstance(groups, dict):
        for members in cast("dict[str, Any]", groups).values():
            if isinstance(members, list):
                found.extend(item for item in cast("list[object]", members) if isinstance(item, str))
    return found


def read_pin(path: Path) -> Pin | None:
    """Read the dirigent-cli specifier one ``pyproject.toml`` names, or none when it names no version."""
    try:
        document = tomllib.loads(path.read_text())
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return None
    for line in _requirements(document):
        try:
            requirement = Requirement(line)
        except InvalidRequirement:
            continue
        if canonicalize_name(requirement.name) == DISTRIBUTION and str(requirement.specifier):
            return Pin(project=path.parent, specifier=str(requirement.specifier))
    return None


def find_pin(start: Path | None = None) -> Pin | None:
    """Find the pin of the project the working directory is in: the nearest ``pyproject.toml`` naming dirigent-cli.

    A ``pyproject.toml`` that does not depend on dirigent-cli is walked past, so a package
    nested inside a project does not hide the project's own pin.
    """
    here = (start or Path.cwd()).resolve()
    for directory in [here, *here.parents]:
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            pin = read_pin(candidate)
            if pin is not None:
                return pin
    return None
