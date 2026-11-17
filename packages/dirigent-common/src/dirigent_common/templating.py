"""Rendering text from a Jinja template, sandboxed and bounded.

Every render runs under a budget, enforced from inside the template as it runs, so a render
stops itself rather than waiting to be abandoned:

* each loop pass, call and filter is a step, and a render takes at most
  :data:`RENDER_STEPS` of them and runs at most the time it was given;
* no single string or list a template builds may hold more than the larger of
  :data:`VALUE_CAP` and the output cap, and a render builds at most :data:`WORK_FACTOR` times
  that in all;
* no number a template computes may hold more than :data:`NUMBER_BITS` bits;
* an operation whose result size follows from its operands -- ``*``, ``+``, ``%``, ``~``, a
  padding width, ``replace``, ``join``, ``indent`` -- is measured before it runs.

The operators ``+``, ``*``, ``**`` and ``%`` and every filter are evaluated only at render,
never folded into a constant when a template is compiled, so compiling a template costs no
more than reading it.
"""

import asyncio
import json
import re
import string
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextvars import ContextVar
from datetime import datetime, timedelta
from typing import Any, Final, cast

import jinja2
import jinja2.compiler
import jinja2.nodes
import jinja2.runtime
import jinja2.sandbox
import jinja2.visitor

from dirigent_common.durations import format_duration
from dirigent_common.messages import (
    RENDER_TOO_LARGE,
    TEMPLATE_FAILED,
    TEMPLATE_LINE,
    TEMPLATE_NO_INCLUDE,
    TEMPLATE_NO_SUCH_TEMPLATE,
    TEMPLATE_NUMBER_TOO_LARGE,
    TEMPLATE_STOPPED,
    TEMPLATE_SUM_OF_NUMBERS,
    TEMPLATE_TOO_MANY_STEPS,
    TEMPLATE_TOO_MUCH_WORK,
    TEMPLATE_TOO_SLOW,
    TEMPLATE_VALUE_TOO_LARGE,
    TEMPLATE_WIDTH_FROM_ARGUMENTS,
    raised_detail,
)
from dirigent_common.sizes import format_size

#: The longest a render runs before it stops itself.
RENDER_WITHIN: Final = timedelta(seconds=5)

#: The steps a render may take: one per loop pass, call and filter.
RENDER_STEPS: Final = 1_000_000

#: The characters or items one value a template builds may hold, when the output cap is smaller.
VALUE_CAP: Final = 1024 * 1024

#: How many times its value cap a render may build in all, counting every intermediate value.
WORK_FACTOR: Final = 32

#: The bits one number a template computes may hold.
NUMBER_BITS: Final = 4096


class TemplateError(Exception):
    """A template that does not compile, or that failed while it was rendering."""


class TemplateTooCostly(TemplateError):
    """A render that passed its budget of steps, time, value size, total work or number size."""


class RenderTooLarge(Exception):
    """A render that passed the size cap and was cut off."""

    def __init__(self, limit: int) -> None:
        """Name the cap, since the fix is a smaller template or a larger setting."""
        super().__init__(RENDER_TOO_LARGE.render(limit=format_size(limit)))
        self.limit = limit


class _Budget:
    """What one render may still spend, and the event that stops it sooner."""

    __slots__ = ("deadline", "steps", "stopped", "value_cap", "within", "work", "work_cap")

    def __init__(self, *, within: timedelta, stopped: threading.Event | None, value_cap: int) -> None:
        self.within = within
        self.deadline = time.monotonic() + within.total_seconds()
        self.stopped = stopped
        self.steps = 0
        self.value_cap = value_cap
        self.work = 0
        self.work_cap = WORK_FACTOR * value_cap


_BUDGET: ContextVar[_Budget | None] = ContextVar("dirigent_render_budget", default=None)


def _value_cap() -> int:
    """The size one value may reach in the render under way."""
    budget = _BUDGET.get()
    return VALUE_CAP if budget is None else budget.value_cap


def _step() -> None:
    """Spend one step of the render under way, stopping it once its steps or its time run out."""
    budget = _BUDGET.get()
    if budget is None:
        return
    budget.steps += 1
    if budget.steps > RENDER_STEPS:
        raise TemplateTooCostly(TEMPLATE_TOO_MANY_STEPS.render(limit=f"{RENDER_STEPS:,}"))
    if budget.stopped is not None and budget.stopped.is_set():
        raise TemplateTooCostly(TEMPLATE_STOPPED.render())
    if time.monotonic() > budget.deadline:
        raise TemplateTooCostly(TEMPLATE_TOO_SLOW.render(within=format_duration(budget.within)))


def _too_large(cap: int) -> TemplateTooCostly:
    """Refuse a value past the cap."""
    return TemplateTooCostly(TEMPLATE_VALUE_TOO_LARGE.render(limit=f"{cap:,}"))


def _refuse_past(size: int) -> None:
    """Refuse a value that would hold more than one value may."""
    cap = _value_cap()
    if size > cap:
        raise _too_large(cap)


def _built(value: object) -> None:
    """Count a string or a list a template built against the value cap and the render's total."""
    if not isinstance(value, str | bytes | list | tuple | dict):
        return
    size = len(cast("str | bytes | list[object] | tuple[object, ...] | dict[object, object]", value))
    _refuse_past(size)
    budget = _BUDGET.get()
    if budget is None:
        return
    budget.work += size
    if budget.work > budget.work_cap:
        raise TemplateTooCostly(TEMPLATE_TOO_MUCH_WORK.render(limit=f"{budget.work_cap:,}"))


def _is_int(value: object) -> bool:
    """Whether a value is an integer and not a boolean."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_sequence(value: object) -> bool:
    """Whether a value is text or a list, which ``*`` repeats and ``+`` joins."""
    return isinstance(value, str | bytes | list | tuple)


def _is_container(value: object) -> bool:
    """Whether a value holds other values, which printing spells out one by one."""
    return isinstance(value, Mapping | list | tuple | set | frozenset)


def _measure(value: object) -> tuple[int, int]:
    """Count the characters and items a value spells out as text, and how deeply it nests.

    Stops with a refusal as soon as the count passes the value cap, so a list holding the same
    long string many times is refused before anything spells it out.
    """
    cap = _value_cap()
    size = 0
    depth = 0
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        item, level = pending.pop()
        depth = max(depth, level)
        if isinstance(item, str | bytes):
            size += len(item)
        elif isinstance(item, Mapping):
            mapping = cast("Mapping[object, object]", item)
            size += 1 + len(mapping)
            pending.extend((key, level + 1) for key in mapping)
            pending.extend((one, level + 1) for one in mapping.values())
        elif isinstance(item, list | tuple | set | frozenset):
            size += 1
            pending.extend((one, level + 1) for one in cast("Iterable[object]", item))
        elif _is_int(item):
            size += cast("int", item).bit_length() // 3 + 1
        else:
            size += 1
        if size > cap:
            raise _too_large(cap)
    return size, depth


def _check_number(bits: int) -> None:
    """Refuse a number that would hold more bits than one may."""
    if bits > NUMBER_BITS:
        raise TemplateTooCostly(TEMPLATE_NUMBER_TOO_LARGE.render(limit=f"{NUMBER_BITS:,}"))


def _check_width(digits: str | None) -> None:
    """Refuse a width or a precision past the value cap, or one taken from the arguments."""
    if digits is None:
        return
    if digits == "*" or "{" in digits:
        raise TemplateTooCostly(TEMPLATE_WIDTH_FROM_ARGUMENTS.render())
    cap = _value_cap()
    if len(digits) > len(str(cap)) or int(digits) > cap:
        raise _too_large(cap)


#: One ``%`` conversion: its mapping key, flags, width, precision, length modifier and type.
_PRINTF: Final = re.compile(r"%(?:\([^)]*\))?[#0\- +]*(\*|\d+)?(?:\.(\*|\d+))?[hlL]?[a-zA-Z%]")

#: Every run of digits in a ``str.format`` spec, the width and the precision among them.
_DIGITS: Final = re.compile(r"\d+")


def _check_printf(text: str, arguments: object) -> None:
    """Measure a ``%`` format before it runs: its widths, and what it spells out."""
    for match in _PRINTF.finditer(text):
        _check_width(match.group(1))
        _check_width(match.group(2))
    _measure(arguments)


def _check_format(text: str, arguments: object) -> None:
    """Measure a ``str.format`` before it runs: its widths, and what it spells out."""
    for _, _, spec, _ in string.Formatter().parse(text):
        if not spec:
            continue
        if "{" in spec:
            _check_width(spec)
        for digits in _DIGITS.findall(spec):
            _check_width(digits)
    _measure(arguments)


def _check_replace(text: object, old: object, new: object, count: object = None) -> None:
    """Measure what replacing ``old`` with ``new`` in ``text`` would build, before it runs."""
    if not (isinstance(text, str) and isinstance(old, str) and isinstance(new, str)):
        return
    found = text.count(old) if old else len(text) + 1
    if _is_int(count) and cast("int", count) >= 0:
        found = min(found, cast("int", count))
    _refuse_past(len(text) + found * (len(new) - len(old)))


def _check_join(separator: str | bytes, parts: object) -> list[object] | None:
    """Measure joining ``parts`` with ``separator`` before it runs, handing back the parts read once."""
    if isinstance(parts, str | bytes):
        _refuse_past(len(parts) * (1 + len(separator)))
        return None
    if not isinstance(parts, Iterable) or isinstance(parts, jinja2.Undefined):
        return None
    read: list[object] = []
    for part in cast("Iterable[object]", parts):
        read.append(part)
        _refuse_past(len(read))
    size, _ = _measure(read)
    _refuse_past(size + max(len(read) - 1, 0) * len(separator))
    return read


def _check_binop(operator: str, left: object, right: object) -> None:
    """Measure what an intercepted operator would build, before it runs."""
    if operator == "**":
        if _is_int(left) and _is_int(right) and cast("int", right) > 0 and abs(cast("int", left)) > 1:
            _check_number(cast("int", right) * cast("int", left).bit_length())
    elif operator == "*":
        if _is_int(left) and _is_int(right):
            _check_number(cast("int", left).bit_length() + cast("int", right).bit_length())
        elif _is_int(right) and _is_sequence(left):
            _refuse_past(_measure(left)[0] * max(cast("int", right), 0))
        elif _is_int(left) and _is_sequence(right):
            _refuse_past(_measure(right)[0] * max(cast("int", left), 0))
    elif operator == "+":
        if _is_sequence(left) and _is_sequence(right):
            _refuse_past(_measure(left)[0] + _measure(right)[0])
    elif operator == "%" and isinstance(left, str):
        _check_printf(left, right)


#: The string methods that pad to a width they are given.
_PADDING: Final = frozenset({"center", "ljust", "rjust", "zfill"})


def _check_call(function: object, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[Any, ...]:
    """Measure what a string method would build before it runs, handing back the arguments to call it with."""
    owner = getattr(function, "__self__", None)
    if not isinstance(owner, str | bytes):
        return args
    name = getattr(function, "__name__", "")
    first = args[0] if args else None
    if name in _PADDING:
        width = first if first is not None else kwargs.get("width")
        if _is_int(width):
            _refuse_past(cast("int", width))
    elif name == "expandtabs":
        tabs = first if first is not None else kwargs.get("tabsize", 8)
        if _is_int(tabs):
            _refuse_past(len(owner) * max(cast("int", tabs), 1))
    elif name == "replace" and len(args) >= 2:
        _check_replace(owner, args[0], args[1], args[2] if len(args) > 2 else kwargs.get("count"))
    elif name == "join" and args:
        read = _check_join(owner, first)
        if read is not None:
            return (read, *args[1:])
    elif name == "translate" and isinstance(first, Mapping):
        table = cast("Mapping[object, object]", first)
        longest = max((len(one) for one in table.values() if isinstance(one, str | bytes)), default=1)
        _refuse_past(len(owner) * max(longest, 1))
    return args


#: The filters that read a list or a mapping as one, rather than spelling it out as text.
_READS_CONTAINERS: Final = frozenset(
    {
        "attr",
        "batch",
        "count",
        "d",
        "default",
        "dictsort",
        "first",
        "groupby",
        "items",
        "join",
        "last",
        "length",
        "list",
        "map",
        "max",
        "min",
        "random",
        "reject",
        "rejectattr",
        "reverse",
        "select",
        "selectattr",
        "slice",
        "sort",
        "sum",
        "unique",
    }
)


def _argument(args: tuple[Any, ...], kwargs: dict[str, Any], index: int, name: str, default: object = None) -> object:
    """Read one filter argument, given by position or by name."""
    return args[index] if len(args) > index else kwargs.get(name, default)


def _check_filter(name: str, value: object, args: tuple[Any, ...], kwargs: dict[str, Any]) -> object:
    """Measure what a filter would build before it runs, handing back the value to filter."""
    for argument in (*args, *kwargs.values()):
        if _is_int(argument):
            _refuse_past(abs(cast("int", argument)))
    if name not in _READS_CONTAINERS and _is_container(value):
        size, depth = _measure(value)
        indent = _argument(args, kwargs, 0, "indent")
        if name == "tojson" and _is_int(indent):
            _refuse_past(size * (1 + max(cast("int", indent), 0) * depth))
    if name == "join":
        separator = _argument(args, kwargs, 0, "d", "")
        if isinstance(separator, str):
            read = _check_join(separator, value)
            return value if read is None else read
    if name == "sum" and not isinstance(_argument(args, kwargs, 1, "start", 0), int | float):
        raise TemplateTooCostly(TEMPLATE_SUM_OF_NUMBERS.render())
    if not isinstance(value, str):
        return value
    if name == "indent":
        width = _argument(args, kwargs, 0, "width", 4)
        each = len(width) if isinstance(width, str) else (cast("int", width) if _is_int(width) else 0)
        _refuse_past(len(value) + (value.count("\n") + 1) * max(each, 0))
    elif name == "wordwrap":
        wrap = _argument(args, kwargs, 2, "wrapstring")
        if isinstance(wrap, str):
            _refuse_past(len(value) * (1 + len(wrap)))
    elif name == "replace":
        _check_replace(
            value,
            _argument(args, kwargs, 0, "old"),
            _argument(args, kwargs, 1, "new"),
            _argument(args, kwargs, 2, "count"),
        )
    elif name == "format":
        _check_printf(value, (args, kwargs))
    return value


def _bounded_filter(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a filter so each use is a step, is measured before it runs, and counts what it built.

    The wrapper takes the render's context, which also keeps Jinja from running the filter
    over constants while it compiles.
    """
    passes = getattr(getattr(function, "jinja_pass_arg", None), "name", None)

    @jinja2.pass_context
    def bounded(context: jinja2.runtime.Context, value: object = None, /, *args: Any, **kwargs: Any) -> object:
        _step()
        value = _check_filter(name, value, args, kwargs)
        if passes == "context":
            result = function(context, value, *args, **kwargs)
        elif passes == "eval_context":
            result = function(context.eval_ctx, value, *args, **kwargs)
        elif passes == "environment":
            result = function(context.environment, value, *args, **kwargs)
        else:
            result = function(value, *args, **kwargs)
        _built(result)
        return result

    bounded.__name__ = getattr(function, "__name__", name)
    bounded.__doc__ = function.__doc__
    return bounded


class _Bounding(jinja2.visitor.NodeTransformer):
    """Route every ``for`` loop's iterable and every ``~`` through the environment's bounded forms."""

    def __init__(self, environment: jinja2.Environment) -> None:
        self.environment = environment

    def _through(self, attribute: str, node: jinja2.nodes.Node, argument: jinja2.nodes.Expr) -> jinja2.nodes.Call:
        """Call one of the environment's bounded forms on an expression."""
        call = jinja2.nodes.Call(
            jinja2.nodes.EnvironmentAttribute(attribute, lineno=node.lineno),
            [argument],
            [],
            None,
            None,
            lineno=node.lineno,
        )
        call.set_environment(self.environment)
        return call

    def visit_For(self, node: jinja2.nodes.For) -> jinja2.nodes.Node:
        """Count each pass of the loop as a step."""
        self.generic_visit(node)
        node.iter = self._through("bounded_iter", node, cast("jinja2.nodes.Expr", node.iter))
        return node

    def visit_Concat(self, node: jinja2.nodes.Concat) -> jinja2.nodes.Node:
        """Measure a ``~`` before it joins its parts."""
        self.generic_visit(node)
        return self._through("bounded_concat", node, jinja2.nodes.List(node.nodes, lineno=node.lineno))


class _BoundedCodeGenerator(jinja2.compiler.CodeGenerator):
    """Compile a template with its loops and its ``~`` routed through the bounded forms."""

    def visit_Template(self, node: jinja2.nodes.Template, frame: jinja2.compiler.Frame | None = None) -> None:
        """Rewrite the tree, then compile it as Jinja does."""
        _Bounding(self.environment).visit(node)
        super().visit_Template(node, frame)


class BoundedEnvironment(jinja2.sandbox.ImmutableSandboxedEnvironment):
    """The immutable sandbox, with every step, value and number a template takes or builds bounded."""

    intercepted_binops: frozenset[str] = frozenset({"+", "*", "**", "%"})
    code_generator_class = _BoundedCodeGenerator

    def call_binop(self, context: jinja2.runtime.Context, operator: str, left: Any, right: Any) -> Any:
        """Measure an arithmetic or a format operator before it runs, and count what it built."""
        _check_binop(operator, left, right)
        result = super().call_binop(context, operator, left, right)
        _built(result)
        return result

    def call(self, context: jinja2.runtime.Context, function: Any, /, *args: Any, **kwargs: Any) -> Any:
        """Count a call as a step, measure a string method before it runs, and count what it built."""
        _step()
        args = _check_call(function, args, kwargs)
        result = super().call(context, function, *args, **kwargs)
        _built(result)
        return result

    def wrap_str_format(self, value: Any) -> Callable[..., str] | None:
        """Measure a ``str.format`` or ``str.format_map`` before it runs."""
        wrapped = super().wrap_str_format(value)
        if wrapped is None:
            return None
        text = cast("str", value.__self__)

        def bounded(*args: Any, **kwargs: Any) -> str:
            _check_format(text, (args, kwargs))
            result = wrapped(*args, **kwargs)
            _built(result)
            return result

        return bounded

    def bounded_iter(self, iterable: Iterable[Any]) -> Iterator[Any]:
        """Hand on a loop's items, spending a step on each."""
        for item in iterable:
            _step()
            yield item

    def bounded_concat(self, parts: list[Any]) -> str:
        """Join the parts of a ``~`` as text, refusing a result past the value cap before it is built."""
        texts: list[str] = []
        size = 0
        for part in parts:
            _measure(part)
            text = str(part)
            size += len(text)
            _refuse_past(size)
            texts.append(text)
        joined = "".join(texts)
        _built(joined)
        return joined


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


def as_text(value: object) -> str:
    """Render a JSON value as the text it reads as inside a larger string.

    A list or an object is its compact JSON, in the order it was written; a boolean is
    ``true`` or ``false``; null is nothing; anything else is its plain text.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)
    return str(value)


def _finalize(value: object) -> object:
    """Render what a ``{{ ... }}`` prints: JSON values as ``as_text`` reads them, the rest as Jinja does."""
    if _is_container(value):
        _measure(value)
    if value is None or isinstance(value, bool | dict | list):
        return as_text(cast("object", value))
    return value


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
#: internals or mutate what it was handed; bounded, so a render stops itself.
ENVIRONMENT: Final = BoundedEnvironment(
    loader=None,
    autoescape=False,
    undefined=SilentUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
    finalize=_finalize,
)
ENVIRONMENT.filters["duration"] = duration_filter
ENVIRONMENT.filters["bytes"] = bytes_filter
ENVIRONMENT.filters["iso"] = iso_filter
ENVIRONMENT.filters.update({name: _bounded_filter(name, function) for name, function in ENVIRONMENT.filters.items()})
ENVIRONMENT.globals.pop("lipsum", None)


def compile_template(source: str) -> jinja2.Template:
    """Compile a template, naming the line a syntax error is on."""
    try:
        return ENVIRONMENT.from_string(source)
    except jinja2.TemplateSyntaxError as error:
        raise TemplateError(TEMPLATE_LINE.render(line=error.lineno, detail=error.message)) from error


def render(
    source: str | jinja2.Template,
    context: Mapping[str, Any],
    *,
    max_bytes: int,
    within: timedelta = RENDER_WITHIN,
    stopped: threading.Event | None = None,
) -> str:
    """Render a template against a context, refusing to build more than ``max_bytes`` of text.

    The cap is enforced as the text is generated, so a runaway loop stops at the cap rather
    than after it has built the whole string. The render's budget -- its steps, ``within``,
    and ``stopped`` staying unset -- is checked as it runs, so a render that would not end
    stops itself as a ``TemplateTooCostly``.

    Anything a template does while it renders -- dividing by zero, a filter refusing what it
    was handed, a macro that recurses, an object in the context that raises when it is read --
    leaves as a ``TemplateError``, so text that could not be produced never takes down the
    work that asked for it.
    """
    template = compile_template(source) if isinstance(source, str) else source
    chunks: list[str] = []
    size = 0
    token = _BUDGET.set(_Budget(within=within, stopped=stopped, value_cap=max(max_bytes, VALUE_CAP)))
    try:
        for chunk in template.generate(dict(context)):
            chunks.append(chunk)
            size += len(chunk.encode())
            if size > max_bytes:
                raise RenderTooLarge(max_bytes)
    except (RenderTooLarge, TemplateError):
        raise
    except (jinja2.TemplateNotFound, jinja2.TemplatesNotFound) as error:
        raise TemplateError(TEMPLATE_NO_SUCH_TEMPLATE.render(name=error.message)) from error
    except (jinja2.UndefinedError, jinja2.exceptions.SecurityError) as error:
        raise TemplateError(TEMPLATE_FAILED.render(detail=str(error))) from error
    except TypeError as error:
        # With no loader, include, import and extends fail here rather than at compile.
        if "no loader" in str(error):
            raise TemplateError(TEMPLATE_NO_INCLUDE.render()) from error
        raise TemplateError(TEMPLATE_FAILED.render(detail=str(error))) from error
    except Exception as error:
        raise TemplateError(TEMPLATE_FAILED.render(detail=raised_detail(error))) from error
    finally:
        _BUDGET.reset(token)
    return "".join(chunks)


async def render_off_loop(
    source: str | jinja2.Template,
    context: Mapping[str, Any],
    *,
    max_bytes: int,
    within: timedelta = RENDER_WITHIN,
) -> str:
    """Render on a worker thread, so the event loop runs on while the template does.

    A caller that stops waiting -- a step's timeout, a cancelled task -- stops the render too,
    at its next step.
    """
    stopped = threading.Event()
    try:
        return await asyncio.to_thread(render, source, context, max_bytes=max_bytes, within=within, stopped=stopped)
    finally:
        stopped.set()
