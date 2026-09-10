"""Process logging: one structlog chain, with the stdlib bridged into it.

:func:`configure_logging` belongs to whichever CLI command owns the process, and is never
called at import time by a library module.
"""

import logging
import os
import sys
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Literal

import structlog
from structlog.typing import EventDict, Processor

from dirigent_core.protocol import Paint, adopt, console

if TYPE_CHECKING:
    from typing import TextIO

PACKAGE_LOGGER = "dirigent"

#: Where a container names the spelling once, for a process and for a command alike.
LOG_FORMAT_ENV = "DIRIGENT_LOG_FORMAT"

#: Third-party loggers that ship their own handlers and must be pointed at ours instead.
BRIDGED_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "gunicorn.error",
    "gunicorn.access",
    "sqlalchemy.engine",
    "httpx2",
    "alembic",
)

#: Loggers that render a raw request line, and therefore need the credential scrubber.
ACCESS_LOGGERS = ("uvicorn.access", "gunicorn.access")

#: Libraries floored above DEBUG even when the process runs at DEBUG; the floor is a
#: parameter rather than a constant so a caller can lift it. The queue clients are floored at
#: CRITICAL: they log a refused connection as an error of their own, and the check or the step
#: that made the call reports the same failure.
NOISY_LOGGERS: dict[str, int] = {
    "aiosqlite": logging.INFO,
    "asyncio": logging.INFO,
    "httpcore2": logging.INFO,
    "aiokafka": logging.CRITICAL,
    "aiormq": logging.CRITICAL,
}

#: Marks the handler this module owns, so repeated configuration never stacks handlers.
_OWNED = "_dirigent_handler"

#: Path prefixes whose *next* segment is a credential rather than an identifier. A webhook
#: token is the entire authentication for a delivery, and span names, span attributes and
#: access log lines are read by people who may not start the pipeline, so the segment is
#: replaced with a placeholder before it reaches any of them.
SECRET_PATH_PREFIXES = ("/hooks/",)

#: Marks the log filter this module owns, so repeated configuration never stacks filters.
_OWNED_FILTER = "_dirigent_filter"

#: Where a foreign logger is floored when verbosity was a request for dirigent's own reasoning.
FOREIGN_FLOOR = logging.WARNING

type LogFormat = Literal["console", "json"]


def redact_path(path: str) -> str:
    """Replace a credential-bearing path segment with a placeholder."""
    for prefix in SECRET_PATH_PREFIXES:
        if path.startswith(prefix):
            return f"{prefix}{{token}}"
    return path


class RedactAccessPath(logging.Filter):
    """Scrub credential-bearing paths out of uvicorn's access log records.

    Uvicorn formats ``%s - "%s %s HTTP/%s" %d`` from ``record.args``, whose third element is
    the request path; for ``POST /hooks/<token>`` that path is a live credential.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the path argument in place, and always keep the record."""
        args = record.args
        if isinstance(args, tuple) and len(args) > 2 and isinstance(args[2], str):
            redacted = redact_path(args[2])
            if redacted != args[2]:
                record.args = (*args[:2], redacted, *args[3:])
        return True


class CapForeignLoggers(logging.Filter):
    """Drop anything below a floor that dirigent did not log itself.

    Asking for more detail means more of dirigent's own reasoning; sqlalchemy's statements
    and alembic's migration history are a different question, and answering it uninvited
    buries the answer to the one that was asked. ``--debug-all`` is how that is asked for.
    """

    def __init__(self, floor: int = FOREIGN_FLOOR) -> None:
        """Floor every logger outside the package namespace."""
        super().__init__()
        self.floor = floor

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep dirigent's own records, and anybody else's only from the floor upward."""
        if record.levelno >= self.floor:
            return True
        return record.name == PACKAGE_LOGGER or record.name.startswith(f"{PACKAGE_LOGGER}.")


def _shared_processors() -> list[Processor]:
    """Build the processors every event passes through, whichever renderer follows."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]


class GrammarRenderer:
    """Render a logging event as the console line a record is rendered as.

    A command's diagnostics and the run's story are two streams of the same events, so they
    read as one grammar: the same timestamp, the same level column, the same ``[kind
    source]``, the same ``key=value`` tail. What a logging event calls its logger is what a
    record calls its kind.
    """

    def __init__(self, paint: Paint | None = None) -> None:
        """Fix how each part of a line is coloured; unpainted where nothing says."""
        self.paint: Paint = paint if paint is not None else _unpainted

    def __call__(self, _logger: object, _name: str, event_dict: EventDict) -> str:
        """Render one event, falling back to structlog's own shape when it is not one."""
        record = adopt(dict(event_dict))
        if record is None:
            return str(event_dict)
        return console(record, paint=self.paint)


def _unpainted(_role: str, text: str) -> str:
    """Leave a part of a line as it is, for a stream nobody asked to colour."""
    return text


def _renderer_chain(log_format: LogFormat, paint: "Paint | None") -> list[Processor]:
    """Build the tail of the chain the stdlib formatter runs: strip meta, then render."""
    tail: list[Processor] = [structlog.stdlib.ProcessorFormatter.remove_processors_meta]
    if log_format == "json":
        tail.append(structlog.processors.format_exc_info)
        tail.append(structlog.processors.JSONRenderer())
    else:
        tail.append(structlog.processors.format_exc_info)
        tail.append(GrammarRenderer(paint))
    return tail


def silence_stdout() -> None:
    """Point stdout at the void, after whatever was reading it has gone.

    Every later write would raise again, and the interpreter reports a second
    BrokenPipeError while flushing at exit unless the descriptor is replaced.
    """
    try:
        void = os.open(os.devnull, os.O_WRONLY)
        os.dup2(void, sys.stdout.fileno())
        os.close(void)
    except OSError:  # pragma: no cover - stdout is not a real descriptor
        pass


class StreamHandler(logging.StreamHandler["TextIO"]):
    """A stream handler that goes quiet when its reader closes the pipe.

    ``dg dev | dg format`` ends with ctrl-c reaching both, and the formatter exits first.
    Reporting that as a logging error would print a traceback per record for a reader that
    is no longer there.
    """

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - the stdlib names the hook
        """Swallow a broken pipe and stop writing; report anything else as usual."""
        if isinstance(sys.exc_info()[1], BrokenPipeError):
            silence_stdout()
            return
        super().handleError(record)


def own_handlers(logger: logging.Logger) -> list[logging.Handler]:
    """List the handlers this module attached to a logger."""
    return [handler for handler in logger.handlers if getattr(handler, _OWNED, False)]


def configure_logging(
    level: str = "INFO",
    log_format: LogFormat = "console",
    *,
    floors: Mapping[str, int] | None = None,
    cap_foreign: bool = False,
    stream: "TextIO | None" = None,
    paint: "Paint | None" = None,
) -> None:
    """Point structlog and the standard library at one shared, formatted handler.

    Structlog events are wrapped for the stdlib formatter rather than rendered inline, so a
    record from SQLAlchemy and an event from the engine come out in the same shape.

    A command's logging is diagnostics beside its answer and goes to stderr, which is the
    default. A process whose stdout *is* its record stream passes ``stream=sys.stdout``.

    The console rendering is the record grammar, so a command's diagnostics read like its
    story rather than like a second program starting. ``paint`` says how to colour it; the
    caller supplies that, because what a terminal may be sent is the caller's to know.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)

    structlog.configure(
        processors=[*_shared_processors(), structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    handler = StreamHandler(sys.stderr if stream is None else stream)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=_shared_processors(),
            processors=_renderer_chain(log_format, paint),
        )
    )
    if cap_foreign:
        handler.addFilter(CapForeignLoggers())
    setattr(handler, _OWNED, True)

    root = logging.getLogger()
    for existing in own_handlers(root):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(numeric_level)

    for name in BRIDGED_LOGGERS:
        bridged = logging.getLogger(name)
        bridged.handlers.clear()
        bridged.setLevel(logging.NOTSET)
        bridged.propagate = True

    for name in ACCESS_LOGGERS:
        access = logging.getLogger(name)
        for existing_filter in [f for f in access.filters if getattr(f, _OWNED_FILTER, False)]:
            access.removeFilter(existing_filter)
        scrubber = RedactAccessPath()
        setattr(scrubber, _OWNED_FILTER, True)
        access.addFilter(scrubber)

    # Reset first, so lifting a floor actually lifts it: configuration is called more than
    # once in a process and must be idempotent.
    applied = NOISY_LOGGERS if floors is None else floors
    for name in {*NOISY_LOGGERS, *applied}:
        logging.getLogger(name).setLevel(logging.NOTSET)
    for name, floor in applied.items():
        logging.getLogger(name).setLevel(max(numeric_level, floor))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound logger under the package name."""
    full_name = PACKAGE_LOGGER if name is None else f"{PACKAGE_LOGGER}.{name}"
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(full_name)
    return logger


#: The package's stdlib logger, held so a hot path can ask its level without a lookup.
_package_logger = logging.getLogger(PACKAGE_LOGGER)


def debug_kept() -> bool:
    """Whether the process log would keep a debug event from this package.

    A caller on a hot path asks before building the event: structlog filters the event out
    only after its arguments have been rendered by the caller.
    """
    return _package_logger.isEnabledFor(logging.DEBUG)


def bind_context(**context: Any) -> None:
    """Bind values every subsequent log line in this task carries."""
    structlog.contextvars.bind_contextvars(**context)


def unbind_context(*keys: str) -> None:
    """Drop specific bound values."""
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """Drop every bound value."""
    structlog.contextvars.clear_contextvars()


@contextmanager
def log_context(**context: Any) -> Generator[None]:
    """Bind context for the duration of a block and restore what was bound before it."""
    tokens = structlog.contextvars.bind_contextvars(**context)
    try:
        yield
    finally:
        structlog.contextvars.reset_contextvars(**tokens)
