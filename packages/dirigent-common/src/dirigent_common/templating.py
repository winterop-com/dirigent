"""Rendering text from a Jinja template, sandboxed and bounded."""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Final

import jinja2
import jinja2.sandbox

from dirigent_common.durations import format_duration
from dirigent_common.sizes import format_size


class TemplateError(Exception):
    """A template that does not compile, or that failed while it was rendering."""


class RenderTooLarge(Exception):
    """A render that passed the size cap and was cut off."""

    def __init__(self, limit: int) -> None:
        """Name the cap, since the fix is a smaller template or a larger setting."""
        super().__init__(f"the rendered text exceeded {format_size(limit)}")
        self.limit = limit


class SilentUndefined(jinja2.ChainableUndefined):
    """An undefined name that renders as the empty string and never fails a render.

    Jinja's own ``Undefined`` already renders empty, iterates empty, is falsy and has length
    zero, and ``ChainableUndefined`` already chains through attribute and item access; the
    operators are the paths that raise, so those are the ones overridden here.

    A sandbox refusal reaches a template as an undefined too, carrying ``SecurityError``
    rather than ``UndefinedError``. That one still fails: it is a template reaching outside
    the sandbox, not a fact the run does not have.
    """

    __slots__ = ()

    def _refuse_if_unsafe(self) -> None:
        """Fail when this undefined stands for something the sandbox refused."""
        if self._undefined_exception is not jinja2.UndefinedError:
            self._fail_with_undefined_error()

    def __str__(self) -> str:
        """Render as nothing."""
        self._refuse_if_unsafe()
        return ""

    def _quiet(self, *args: object, **kwargs: object) -> "SilentUndefined":
        """Carry the undefined through an operator or a call, so the result renders empty."""
        self._refuse_if_unsafe()
        return self

    def _false(self, *args: object, **kwargs: object) -> bool:
        """Answer an ordering comparison against an undefined."""
        self._refuse_if_unsafe()
        return False

    def _zero(self) -> int:
        """Read an undefined as a number."""
        self._refuse_if_unsafe()
        return 0

    # Each of these is a raising method on the base class, so replacing one widens a return
    # type both checkers read as Never.
    __add__ = __radd__ = __sub__ = __rsub__ = _quiet  # type: ignore[assignment]
    __mul__ = __rmul__ = __truediv__ = __rtruediv__ = _quiet  # type: ignore[assignment]
    __floordiv__ = __rfloordiv__ = __mod__ = __rmod__ = _quiet  # type: ignore[assignment]
    __pow__ = __rpow__ = __pos__ = __neg__ = _quiet  # type: ignore[assignment]
    __call__ = _quiet  # type: ignore[assignment]
    __lt__ = __le__ = __gt__ = __ge__ = _false  # type: ignore[assignment]
    __int__ = __float__ = _zero  # type: ignore[assignment]


def duration_filter(value: object) -> str:
    """Render a count of milliseconds as a humane duration."""
    if not isinstance(value, int | float) or isinstance(value, bool):
        return ""
    return format_duration(timedelta(milliseconds=value))


def bytes_filter(value: object) -> str:
    """Render a count of bytes as a humane size."""
    if not isinstance(value, int) or isinstance(value, bool):
        return ""
    return format_size(value)


def iso_filter(value: object) -> str:
    """Render a moment as ISO 8601, accepting one that is already a string."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return ""


#: The one environment every template renders in: no loader, so ``include``, ``import`` and
#: ``extends`` cannot reach a file; immutable sandbox, so a template cannot reach an object's
#: internals or mutate what it was handed.
ENVIRONMENT: Final = jinja2.sandbox.ImmutableSandboxedEnvironment(
    loader=None,
    autoescape=False,
    undefined=SilentUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)
ENVIRONMENT.filters["duration"] = duration_filter
ENVIRONMENT.filters["bytes"] = bytes_filter
ENVIRONMENT.filters["iso"] = iso_filter


def compile_template(source: str) -> jinja2.Template:
    """Compile a template, naming the line a syntax error is on."""
    try:
        return ENVIRONMENT.from_string(source)
    except jinja2.TemplateSyntaxError as error:
        raise TemplateError(f"line {error.lineno}: {error.message}") from error


def render(source: str | jinja2.Template, context: Mapping[str, Any], *, max_bytes: int) -> str:
    """Render a template against a context, refusing to build more than ``max_bytes`` of text.

    The cap is enforced as the text is generated, so a runaway loop stops at the cap rather
    than after it has built the whole string.
    """
    template = compile_template(source) if isinstance(source, str) else source
    chunks: list[str] = []
    size = 0
    try:
        for chunk in template.generate(dict(context)):
            chunks.append(chunk)
            size += len(chunk.encode())
            if size > max_bytes:
                raise RenderTooLarge(max_bytes)
    except (jinja2.TemplateNotFound, jinja2.TemplatesNotFound) as error:
        raise TemplateError(f"no template named {error.message}: a template cannot pull in another") from error
    except (jinja2.UndefinedError, jinja2.exceptions.SecurityError) as error:
        raise TemplateError(str(error)) from error
    except TypeError as error:
        # With no loader, include, import and extends fail here rather than at compile.
        if "no loader" in str(error):
            raise TemplateError("a template cannot include, import or extend another") from error
        raise TemplateError(str(error)) from error
    return "".join(chunks)
