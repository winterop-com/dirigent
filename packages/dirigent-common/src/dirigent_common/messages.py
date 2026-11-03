"""The catalogue every refusal is rendered from: a stable code, one template, named params.

A refusal is identified by its dotted code and rendered from the English template its
catalogue holds. The params carry the specifics, so a translation can replace the template by
code and render the same refusal in another language without anything else changing.
"""

import re
from collections.abc import Collection, Mapping, Sequence
from datetime import timedelta
from string import Formatter
from types import UnionType
from typing import Any, ClassVar, Final, Self, Union, cast, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field

from dirigent_common.redaction import scrub
from dirigent_common.types import JsonMap

#: A message name: lowercase words joined by underscores, and dotted where a family of
#: refusals groups under one thing, as a health check's do.
NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")

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

YAML_ALIASES_EXPAND_TOO_FAR = COMMON.define(
    "yaml_aliases_expand_too_far",
    "the YAML's aliases would add more than {limit} values once each is written out; "
    "write the repeated parts out in the source, or repeat them less",
)

YAML_ALIASES_WRITE_TOO_MUCH = COMMON.define(
    "yaml_aliases_write_too_much",
    "the YAML's aliases would add more than {limit} bytes of text once each is written out; "
    "write the repeated parts out in the source, or repeat them less",
)

YAML_ALIAS_CYCLE = COMMON.define(
    "yaml_alias_cycle",
    "the YAML holds an alias inside the node it names, and a value cannot be written out that contains itself",
)

YAML_NESTED_TOO_DEEP = COMMON.define("yaml_nested_too_deep", "the YAML nests too deeply to be read")

VALUE_NOT_SHOWN = COMMON.define("value_not_shown", "nested deeper than {limit} levels, not shown")

VALIDATION = Catalogue("validation")

#: Pydantic names the condition, so the second half of a validation code is its own error
#: type and the template is the sentence pydantic wrote: the message is minted on first
#: sight rather than declared, and its text renders the ``msg`` param whole.
_PYDANTIC_TEXT: Final = "{msg}"

#: The one validation message whose wording is ours: an unknown key, with the field it is
#: closest to when the document format knows one.
EXTRA_FORBIDDEN = VALIDATION.define("extra_forbidden", "unknown key{suggestion}")

#: Text a caller wrote that no database stores as written, refused where it arrives.
TEXT_UNSTORABLE = VALIDATION.define(
    "text_unstorable", "holds a NUL character or half a surrogate pair, which cannot be stored; remove it"
)


MISSING = VALIDATION.define("missing", "is required")

AT_MOST = VALIDATION.define("less_than_equal", "must be at most {limit}")

BELOW = VALIDATION.define("less_than", "must be less than {limit}")

AT_LEAST = VALIDATION.define("greater_than_equal", "must be at least {limit}")

ABOVE = VALIDATION.define("greater_than", "must be more than {limit}")

#: Each bound pydantic reports, the key its context names the limit by, and our wording.
_BOUNDS: Final[Mapping[str, tuple[str, Message]]] = {
    "less_than_equal": ("le", AT_MOST),
    "less_than": ("lt", BELOW),
    "greater_than_equal": ("ge", AT_LEAST),
    "greater_than": ("gt", ABOVE),
}

#: How pydantic spells a timedelta bound in an error's context, which is the bound's repr.
_TIMEDELTA_REPR: Final = re.compile(r"^datetime\.timedelta\(((?:\w+=-?[\d.]+(?:, )?)*)\)$")


def _validation_message(error_type: str) -> Message:
    """Name the message one pydantic error type renders through, minting it on first sight."""
    name = error_type if NAME_PATTERN.match(error_type) else re.sub(r"[^a-z0-9_]", "_", error_type.lower())
    return VALIDATION.messages.get(name) or VALIDATION.define(name, _PYDANTIC_TEXT)


def _plain(msg: str) -> str:
    """Say pydantic's sentence as a predicate of the field it is addressed at."""
    if msg.startswith("Value error, "):
        return msg.removeprefix("Value error, ")
    if msg.startswith("Input should be "):
        return "must be " + msg.removeprefix("Input should be ")
    if msg.startswith("Input should "):
        return "must " + msg.removeprefix("Input should ")
    return msg


def _unwrapped(annotation: Any) -> list[Any]:
    """Every type and metadata entry an annotation is made of, through aliases, unions and Annotated."""
    alias = getattr(annotation, "__value__", None)
    if alias is not None:
        return _unwrapped(alias)
    found: list[Any] = [annotation]
    metadata = getattr(annotation, "__metadata__", None)
    if metadata is not None:
        found.extend(metadata)
        for entry in metadata:
            found.extend(getattr(entry, "metadata", ()))
        found.extend(_unwrapped(getattr(annotation, "__origin__", None)))
        return found
    if get_origin(annotation) in (Union, UnionType):
        for member in get_args(annotation):
            found.extend(_unwrapped(member))
    return found


def _field_parts(model: type[BaseModel], location: Sequence[Any]) -> list[Any] | None:
    """What the field a validation error is addressed at is made of, or None where the walk loses it."""
    parts: list[Any] = [model]
    for step in location:
        held = next((one for one in parts if isinstance(one, type) and issubclass(one, BaseModel)), None)
        if held is not None and isinstance(step, str):
            field = held.model_fields.get(step)
            if field is None:
                return None
            parts = [*field.metadata, *_unwrapped(field.annotation)]
            continue
        containers = [one for one in parts if get_origin(one) in (list, dict, tuple, set, frozenset)]
        if not containers:
            return None
        parts = _unwrapped(get_args(containers[0])[-1])
    return parts


def _limit(detail: Mapping[str, Any], key: str, model: type[BaseModel] | None) -> str:
    """The bound a value missed, said the way a document writes it: ``30s``, ``1mb``, ``10``."""
    from dirigent_common.durations import format_duration
    from dirigent_common.sizes import format_size

    parts = _field_parts(model, tuple(detail.get("loc", ()))) if model is not None else None
    if parts is not None:
        bound = next((getattr(one, key) for one in parts if hasattr(one, key) and not isinstance(one, type)), None)
        sized = any(getattr(one, "func", None) is format_size for one in parts)
        if isinstance(bound, timedelta):
            return format_duration(bound)
        if sized and isinstance(bound, int):
            return format_size(bound)
        if bound is not None:
            return str(bound)
    held = cast("Mapping[str, Any]", detail.get("ctx") or {}).get(key)
    if isinstance(held, timedelta):
        return format_duration(held)
    spelled = _TIMEDELTA_REPR.match(str(held)) if held is not None else None
    if spelled is not None:
        named = dict(term.split("=") for term in spelled.group(1).split(", ") if term)
        return format_duration(timedelta(**{name: float(value) for name, value in named.items()}))
    return "the limit" if held is None else str(held)


def validation_issue(detail: Mapping[str, Any], *, suggestion: str = "", model: type[BaseModel] | None = None) -> Issue:
    """Render one pydantic error as an issue, keeping the value that failed out of the params.

    The input value may be a credential or a fragment of a payload, so the params name its
    kind and never carry it. ``model`` is the model that was validated, which is where a
    bound on a duration or a size is read back as a value a document would write.
    """
    location = ".".join(str(part) for part in detail.get("loc", ()))
    params: JsonMap = {"loc": [str(part) for part in detail.get("loc", ())]}
    if "input" in detail:
        params["input_kind"] = type(detail["input"]).__name__
    error_type = str(detail.get("type", "value_error"))
    if error_type == "extra_forbidden":
        return Issue.of(EXTRA_FORBIDDEN, location=location or None, suggestion=suggestion, **params)
    if error_type == "missing":
        return Issue.of(MISSING, location=location or None, **params)
    if error_type in _BOUNDS:
        key, message = _BOUNDS[error_type]
        return Issue.of(message, location=location or None, limit=_limit(detail, key, model), **params)
    params["msg"] = _plain(str(detail.get("msg", "")))
    return Issue.of(_validation_message(error_type), location=location or None, **params)


def validation_issues(errors: Sequence[Mapping[str, Any]], *, model: type[BaseModel] | None = None) -> list[Issue]:
    """Render every pydantic error of one validation as issues."""
    return [validation_issue(detail, model=model) for detail in errors]


#: How much of an exception's own text is kept, where it is stored per attempt or per check.
RAISED_DETAIL_CHARS: Final = 2000


def raised_detail(error: Exception, *, redact: Collection[str] = ()) -> str:
    """Say what an exception said about itself, falling back to its class when it said nothing.

    A Python class name is not a sentence anybody wrote, so it is the last thing left to say
    rather than the first thing said. What comes back is an operator's detail: it belongs in a
    log, in a refusal's params, or in the ``{detail}`` of a message that supplies the sentence
    around it, and never alone in front of a person. ``redact`` is scrubbed before the cut, which
    would otherwise leave a long secret too short to be found.
    """
    detail = scrub(str(error).strip(), redact) or type(error).__name__
    if len(detail) > RAISED_DETAIL_CHARS:
        return f"{detail[:RAISED_DETAIL_CHARS]} [truncated, {len(detail)} characters]"
    return detail
