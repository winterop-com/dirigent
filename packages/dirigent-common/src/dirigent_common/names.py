"""The two name grammars every dirigent identifier obeys, as shared validated types."""

import re
from typing import Annotated, Final

from pydantic import StringConstraints

#: The grammar reads most naturally as ``^[a-z]([a-z0-9]|-(?=[a-z0-9]))*$``, but this
#: pattern is published in JSON Schema and compiled by pydantic-core's Rust engine, which
#: supports no look-ahead. The form below is its exact equivalent: every hyphen must be
#: followed by an alphanumeric, which forbids a trailing hyphen and a doubled one alike.
ENTITY_NAME_PATTERN: Final = r"^[a-z](-?[a-z0-9])*$"

ENTITY_NAME_MAX_LENGTH: Final = 63

STEP_NAME_PATTERN: Final = r"^[a-z][a-z0-9_]*$"

STEP_NAME_MAX_LENGTH: Final = 63

#: An address with one ``@`` and a dotted host, which is as far as a pattern can honestly go.
EMAIL_PATTERN: Final = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

EMAIL_MAX_LENGTH: Final = 320

type EntityName = Annotated[
    str, StringConstraints(pattern=ENTITY_NAME_PATTERN, max_length=ENTITY_NAME_MAX_LENGTH, min_length=1)
]

type StepName = Annotated[
    str, StringConstraints(pattern=STEP_NAME_PATTERN, max_length=STEP_NAME_MAX_LENGTH, min_length=1)
]

type Email = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=EMAIL_PATTERN, max_length=EMAIL_MAX_LENGTH)
]

_ENTITY_NAME = re.compile(ENTITY_NAME_PATTERN)
_STEP_NAME = re.compile(STEP_NAME_PATTERN)


def is_entity_name(value: str) -> bool:
    """Report whether a string is a valid kebab-case entity name."""
    return len(value) <= ENTITY_NAME_MAX_LENGTH and _ENTITY_NAME.fullmatch(value) is not None


def is_step_name(value: str) -> bool:
    """Report whether a string is a valid snake_case step name."""
    return len(value) <= STEP_NAME_MAX_LENGTH and _STEP_NAME.fullmatch(value) is not None


def entity_name_error(label: str, value: str) -> str:
    """Render the one message every entity-name rejection uses, so the advice never varies."""
    return (
        f"{label} {value!r} is not a valid name: names are lowercase letters, digits, and single "
        f"hyphens, start with a letter, end alphanumeric, and are at most "
        f"{ENTITY_NAME_MAX_LENGTH} characters"
    )


def step_name_error(value: str) -> str:
    """Render the one message every step-name rejection uses, including why it differs."""
    return (
        f"step name {value!r} is not valid: step names are snake_case ({STEP_NAME_PATTERN}), because "
        f"they appear inside ${{steps.<name>.output.…}} where a hyphen or a dot would be ambiguous"
    )
