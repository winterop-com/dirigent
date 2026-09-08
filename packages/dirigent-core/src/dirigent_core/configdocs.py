"""Rendering the settings model as the two things a person reads: a page, and an example file.

Both are generated from :class:`~dirigent_core.config.Settings` itself, so a setting added
without a description fails the build rather than shipping an empty line.
"""

import json
import textwrap
from datetime import timedelta
from typing import Any, Final

from pydantic_core import PydanticUndefined

from dirigent_common import as_markdown, format_duration
from dirigent_core.config import Settings

#: Relative to the repository root.
PAGE_PATH: Final = "docs/settings.md"

BANNER: Final = "<!-- Generated from dirigent_core.config.Settings by dirigent_core.configdocs. Do not edit. -->"

PREAMBLE: Final = """# Settings reference

Every setting an instance has, its default, and what it does. This page is generated from the
settings model, so it cannot drift from the code: a setting added either shows up here or
fails the build.

Each one is read from three places, most specific first: a `DIRIGENT_`-prefixed environment
variable, the YAML configuration file, then the default below. `dg init` writes a
`dirigent.example.yaml` holding this same list, commented out, beside the working
`dirigent.yaml` -- so the file a person edits stays short and the whole surface is still
one file away.
"""

#: The settings a scaffolded project sets rather than leaves to a default. Everything else
#: reaches the example file commented out.
SCAFFOLDED: Final[tuple[str, ...]] = ("environment", "log_level", "worker_concurrency")

EXAMPLE_HEADER: Final = """\
# Every setting dirigent has, with its default and what it does.
#
# This file is read, never loaded: dirigent does not look for it. Copy a line into
# dirigent.yaml to change it, or set the environment variable named beside it.
#
# Generated from the settings model, so it lists what this version actually has.
"""

PROJECT_HEADER: Final = """\
# This instance's settings. Everything not named here keeps its default; the whole list,
# with defaults and descriptions, is in dirigent.example.yaml beside this file.
"""


def environment_name(field: str) -> str:
    """Name the environment variable one setting is read from."""
    return f"DIRIGENT_{field.upper()}"


def rendered_default(name: str) -> Any:
    """Read one field's default as the YAML and the table should show it."""
    field = Settings.model_fields[name]
    if field.default is not PydanticUndefined:
        return field.default
    return field.default_factory() if field.default_factory is not None else None  # type: ignore[call-arg]


def described(name: str) -> str:
    """Read what one field is, as a single line, in the spelling markdown reads.

    The first paragraph only. A docstring says what the setting is and then, often, how to
    choose a value and what it interacts with; a reference table wants the first of those,
    and a page of tuning advice inside one cell is unreadable. The rest stays where somebody
    reading the code will find it.
    """
    description = Settings.model_fields[name].description or ""
    return one_line(first_paragraph(description))


def first_paragraph(text: str) -> str:
    """Take what a description says before its first blank line."""
    return text.strip().split("\n\n", 1)[0]


def one_line(text: str) -> str:
    """Flatten a description onto one line, in the spelling markdown reads."""
    return as_markdown(" ".join(text.split()))


def _commented(text: str, width: int = 92) -> list[str]:
    """Wrap a description into comment lines, in the spelling a YAML file reads."""
    return [f"# {line}" for line in textwrap.wrap(text.replace("`", ""), width=width)] or ["#"]


def _yaml_value(value: Any) -> str:
    """Render one default the way the YAML file writes it."""
    if value is None:
        return "null"
    if isinstance(value, timedelta):
        return json.dumps(format_duration(value))
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    return json.dumps(str(value))


def example_document() -> str:
    """Render the commented reference file, every setting with its default and description."""
    lines = [EXAMPLE_HEADER]
    for name in Settings.model_fields:
        lines.extend(_commented(described(name)))
        lines.append(f"# {environment_name(name)}")
        lines.append(f"# {name}: {_yaml_value(rendered_default(name))}")
        lines.append("")
    return "\n".join(lines)


def project_document(**chosen: Any) -> str:
    """Render the working configuration file, holding only what a project is likely to change."""
    values = {name: chosen.get(name, rendered_default(name)) for name in SCAFFOLDED}
    body = "\n".join(f"{name}: {_yaml_value(value)}" for name, value in values.items())
    return f"{PROJECT_HEADER}\n{body}\n"


def render() -> str:
    """Render the settings reference page."""
    rows = "\n".join(
        f"| `{name}` | `{environment_name(name)}` | `{_yaml_value(rendered_default(name))}` | {described(name)} |"
        for name in Settings.model_fields
    )
    header = "| Setting | Environment | Default | What it does |\n| --- | --- | --- | --- |"
    return f"{BANNER}\n{PREAMBLE}\n{header}\n{rows}\n"
