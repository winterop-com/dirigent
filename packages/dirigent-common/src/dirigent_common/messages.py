"""The catalogue every refusal is rendered from: a stable code, one template, named params.

A refusal is identified by its dotted code and rendered from the English template its
catalogue holds. The params carry the specifics, so a translation can replace the template by
code and render the same refusal in another language without anything else changing.
"""

import re
from string import Formatter
from typing import Any, ClassVar, Final, Self

from pydantic import BaseModel, ConfigDict, Field

from dirigent_common.types import JsonMap

#: A message name: one lowercase word, or several joined by underscores.
NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*$")

#: A catalogue prefix: one or more lowercase segments separated by dots.
PREFIX_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


class MessageError(ValueError):
    """A message was declared with a name or a template the catalogue does not accept."""


class Message(BaseModel):
    """One catalogued refusal: its code, and the template its text is rendered from."""

    model_config = ConfigDict(frozen=True)

    code: str
    """The dotted code, stable API, that identifies this refusal wherever it appears."""

    text: str
    """The English template, with a named field per param the refusal carries."""

    def render(self, **params: Any) -> str:
        """Render the text with the params, refusing to render one the template asks for."""
        try:
            return self.text.format(**params)
        except KeyError as error:
            missing = error.args[0] if error.args else "?"
            raise MessageError(f"{self.code} has no value for {missing!r}") from error

    @property
    def fields(self) -> frozenset[str]:
        """Name every param the template renders."""
        return frozenset(name for _, name, _, _ in Formatter().parse(self.text) if name)


class Catalogue:
    """Every message one package or area owns, minted under the prefix it owns."""

    #: Every catalogue the process has imported, so a test can walk all of them at once.
    all: ClassVar[list["Catalogue"]] = []

    def __init__(self, prefix: str) -> None:
        """Claim a prefix and register the catalogue for the workspace-wide walk."""
        if not PREFIX_PATTERN.match(prefix):
            raise MessageError(f"{prefix!r} is not a prefix: write lowercase segments separated by dots")
        self.prefix = prefix
        self.messages: dict[str, Message] = {}
        Catalogue.all.append(self)

    def define(self, name: str, text: str) -> Message:
        """Mint one message under this catalogue's prefix."""
        if not NAME_PATTERN.match(name):
            raise MessageError(f"{name!r} is not a message name: write lowercase words joined by underscores")
        if name in self.messages:
            raise MessageError(f"{self.prefix}.{name} is defined twice")
        message = Message(code=f"{self.prefix}.{name}", text=text)
        self.messages[name] = message
        return message


class Issue(BaseModel):
    """One problem in a list of them, carrying its own code so it reads like any other refusal."""

    model_config = ConfigDict(frozen=True)

    code: str
    """The dotted code of the message this issue was rendered from."""

    message: str
    """What is wrong, in the terms the person reading it is thinking in."""

    params: JsonMap = Field(default_factory=dict)
    """The specifics the template rendered, for a re-render in another language."""

    location: str | None = None
    """Where the problem is, as a dotted path, when the issue is addressed at a place."""

    @classmethod
    def of(cls, message: Message, /, *, location: str | None = None, **params: Any) -> Self:
        """Build an issue by rendering a catalogued message with its params."""
        return cls(code=message.code, message=message.render(**params), params=params, location=location)

    def __str__(self) -> str:
        """Render the issue as one line, prefixed by where it is when it names a place."""
        return f"{self.location}: {self.message}" if self.location else self.message


COMMON = Catalogue("common")

NEGATIVE_DURATION = COMMON.define(
    "negative_duration",
    "{value} is negative, and a duration is a delay, a cadence, or a budget: "
    "the format has no way to write one that runs backwards",
)

NOT_A_DURATION = COMMON.define(
    "not_a_duration",
    "{value} is not a duration: write a number of seconds, or unit-suffixed terms "
    "such as '30s', '5m', '6h', '1h30m', '250ms' (units: w, d, h, m, s, ms)",
)

NEGATIVE_SIZE = COMMON.define(
    "negative_size",
    "{value} is negative, and a size is a quantity of bytes: it cannot run backwards",
)

NOT_A_SIZE = COMMON.define(
    "not_a_size",
    "{value} is not a size: write a number of bytes, or a unit-suffixed amount such as "
    "'512kb', '64mb', '1.5gb' (units: b, kb, mb, gb, tb, and the kib/mib/gib/tib spelling of each, "
    "all powers of 1024)",
)

NOT_AN_ENTITY_NAME = COMMON.define(
    "not_an_entity_name",
    "{label} {value} is not a valid name: names are lowercase letters, digits, and single "
    "hyphens, start with a letter, end alphanumeric, and are at most {limit} characters",
)

NOT_A_STEP_NAME = COMMON.define(
    "not_a_step_name",
    "step name {value} is not valid: step names are snake_case ({pattern}), because "
    "they appear inside ${{steps.<name>.output.…}} where a hyphen or a dot would be ambiguous",
)

RENDER_TOO_LARGE = COMMON.define("render_too_large", "the rendered text exceeded {limit}")

TEMPLATE_LINE = COMMON.define("template_line", "line {line}: {detail}")

TEMPLATE_NO_INCLUDE = COMMON.define("template_no_include", "a template cannot include, import or extend another")

TEMPLATE_NO_SUCH_TEMPLATE = COMMON.define(
    "template_no_such_template", "no template named {name}: a template cannot pull in another"
)

TEMPLATE_FAILED = COMMON.define("template_failed", "{detail}")

NO_JSON_SPELLING = COMMON.define("no_json_spelling", "a value of type {kind} has no JSON spelling")

VALIDATION = Catalogue("validation")

#: Pydantic names the condition, so the second half of a validation code is its own error
#: type and the template is the sentence pydantic wrote: the message is minted on first
#: sight rather than declared, and its text renders the ``msg`` param whole.
_PYDANTIC_TEXT: Final = "{msg}"

#: The one validation message whose wording is ours: an unknown key, with the field it is
#: closest to when the document format knows one.
EXTRA_FORBIDDEN = VALIDATION.define("extra_forbidden", "unknown key{suggestion}")


def _validation_message(error_type: str) -> Message:
    """Name the message one pydantic error type renders through, minting it on first sight."""
    name = error_type if NAME_PATTERN.match(error_type) else re.sub(r"[^a-z0-9_]", "_", error_type.lower())
    return VALIDATION.messages.get(name) or VALIDATION.define(name, _PYDANTIC_TEXT)


def validation_issue(detail: dict[str, Any], *, suggestion: str = "") -> Issue:
    """Render one pydantic error as an issue, keeping the value that failed out of the params.

    The input value may be a credential or a fragment of a payload, so the params name its
    kind and never carry it.
    """
    location = ".".join(str(part) for part in detail.get("loc", ()))
    params: JsonMap = {"loc": [str(part) for part in detail.get("loc", ())]}
    if "input" in detail:
        params["input_kind"] = type(detail["input"]).__name__
    if detail.get("type") == "extra_forbidden":
        return Issue.of(EXTRA_FORBIDDEN, location=location or None, suggestion=suggestion, **params)
    params["msg"] = str(detail.get("msg", ""))
    return Issue.of(_validation_message(str(detail.get("type", "value_error"))), location=location or None, **params)


def validation_issues(errors: list[dict[str, Any]]) -> list[Issue]:
    """Render every pydantic error of one validation as issues."""
    return [validation_issue(detail) for detail in errors]
