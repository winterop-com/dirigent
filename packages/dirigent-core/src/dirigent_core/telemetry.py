"""OpenTelemetry spans and metrics, off until an exporter is configured.

``opentelemetry-api`` is always imported; without an SDK its providers are the API's own
no-op implementations. The SDK is wired up only when the standard ``OTEL_*`` environment
says where to send data.
"""

import os
import socket
from collections.abc import Callable, Generator, Iterable, Mapping
from contextlib import contextmanager
from typing import Any, Final

from opentelemetry import metrics, trace
from opentelemetry.context import Context
from opentelemetry.metrics import CallbackOptions, Observation
from opentelemetry.trace import Span, SpanKind, Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from dirigent_core.config import Settings
from dirigent_core.logging import get_logger, redact_path

SCOPE: Final = "dirigent"

#: The environment variables that mean "an exporter is configured", per the OTel spec.
EXPORTER_ENV: Final = (
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
    "OTEL_TRACES_EXPORTER",
    "OTEL_METRICS_EXPORTER",
)

#: Exporter values that mean "explicitly off", which the spec defines as valid settings.
DISABLED_VALUES: Final = frozenset({"", "none", "None"})

#: Bucket edges for both duration histograms, in seconds. The SDK's own defaults start at
#: 0, 5, 10, which puts every step a pipeline actually runs in one bucket.
DURATION_BUCKETS: Final = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 300.0, 900.0)

#: How a trace context is written down and read back. A run carries one across processes,
#: so it has to survive a database column and an hour of waiting.
_propagator: Final = TraceContextTextMapPropagator()

_logger = get_logger("telemetry")
_tracer = trace.get_tracer(SCOPE)
_meter = metrics.get_meter(SCOPE)
_configured = False


def exporter_configured(environ: Mapping[str, str] | None = None) -> bool:
    """Report whether the standard environment names somewhere to send telemetry."""
    env = environ if environ is not None else os.environ
    if env.get("OTEL_SDK_DISABLED", "").lower() == "true":
        return False
    return any(env.get(name) not in DISABLED_VALUES and env.get(name) is not None for name in EXPORTER_ENV)


def configure_telemetry(settings: Settings | None = None, *, environ: Mapping[str, str] | None = None) -> bool:
    """Wire up the OpenTelemetry SDK, returning whether telemetry ended up live."""
    global _configured
    if _configured or not exporter_configured(environ):
        return _configured
    try:
        _install_sdk(settings, environ if environ is not None else os.environ)
    except Exception as error:  # telemetry must never be the reason a process fails to start
        _logger.warning("telemetry could not be configured", error=str(error))
        return False
    _configured = True
    _logger.info("telemetry configured", service=SCOPE)
    return True


def reset_telemetry() -> None:
    """Forget that telemetry was configured, so a test can configure it differently."""
    global _configured
    _configured = False


def resource_attributes(settings: Settings | None, environ: Mapping[str, str]) -> dict[str, str]:
    """Build the resource attributes every span and metric carries.

    ``service.instance.id`` is what separates two processes of one service; the standard
    resource environment wins where it already names one.
    """
    from dirigent_core import __version__

    attributes = {
        "service.name": environ.get("OTEL_SERVICE_NAME", SCOPE),
        "service.version": __version__,
        "deployment.environment": settings.environment if settings else "local",
    }
    declared = environ.get("OTEL_RESOURCE_ATTRIBUTES", "").split(",")
    if not any(entry.split("=", 1)[0].strip() == "service.instance.id" for entry in declared):
        attributes["service.instance.id"] = f"{socket.gethostname()}-{os.getpid()}"
    return attributes


def _install_sdk(settings: Settings | None, environ: Mapping[str, str]) -> None:
    """Build the tracer and meter providers from the standard environment."""
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(resource_attributes(settings, environ))
    tracer_provider = TracerProvider(resource=resource)
    span_exporter = _span_exporter(environ)
    if span_exporter is not None:
        tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    metric_exporter = _metric_exporter(environ)
    readers = [PeriodicExportingMetricReader(metric_exporter)] if metric_exporter is not None else []
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))

    global _tracer, _meter
    _tracer = trace.get_tracer(SCOPE)
    _meter = metrics.get_meter(SCOPE)
    register_instruments()


def _optional(module: str, name: str) -> Any:
    """Import an exporter class by name, so the package that speaks the wire stays an extra."""
    import importlib

    return getattr(importlib.import_module(module), name)


def _span_exporter(environ: Mapping[str, str]) -> Any | None:
    """Build the span exporter the environment names, or nothing when it names none."""
    choice = environ.get("OTEL_TRACES_EXPORTER", "otlp")
    if choice in DISABLED_VALUES:
        return None
    if choice == "console":
        return _optional("opentelemetry.sdk.trace.export", "ConsoleSpanExporter")()
    return _optional("opentelemetry.exporter.otlp.proto.http.trace_exporter", "OTLPSpanExporter")()


def _metric_exporter(environ: Mapping[str, str]) -> Any | None:
    """Build the metric exporter the environment names, or nothing when it names none."""
    choice = environ.get("OTEL_METRICS_EXPORTER", "otlp")
    if choice in DISABLED_VALUES:
        return None
    if choice == "console":
        return _optional("opentelemetry.sdk.metrics.export", "ConsoleMetricExporter")()
    return _optional("opentelemetry.exporter.otlp.proto.http.metric_exporter", "OTLPMetricExporter")()


class Gauges:
    """The numbers an operator watches that are levels rather than events."""

    def __init__(self) -> None:
        """Start every level at zero."""
        self.queue_depth = 0
        self.waiting = 0
        self.in_flight = 0
        self.scheduler_lag = 0.0
        self.heartbeat_ages: dict[str, float] = {}
        self.worker: str | None = None

    def observe(
        self,
        *,
        queue_depth: int | None = None,
        waiting: int | None = None,
        scheduler_lag: float | None = None,
        heartbeat_ages: Mapping[str, float] | None = None,
    ) -> None:
        """Record what the engine last saw."""
        if queue_depth is not None:
            self.queue_depth = queue_depth
        if waiting is not None:
            self.waiting = waiting
        if scheduler_lag is not None:
            self.scheduler_lag = scheduler_lag
        if heartbeat_ages is not None:
            self.heartbeat_ages = dict(heartbeat_ages)


gauges = Gauges()

_runs = _meter.create_counter("dirigent.runs", description="Runs by terminal status.")
_steps = _meter.create_counter("dirigent.steps", description="Step attempts by terminal status.")
_step_duration = _meter.create_histogram(
    "dirigent.step.duration",
    unit="s",
    description="How long a step attempt took.",
    explicit_bucket_boundaries_advisory=DURATION_BUCKETS,
)
_block_duration = _meter.create_histogram(
    "dirigent.block.duration",
    unit="s",
    description="How long one block call took.",
    explicit_bucket_boundaries_advisory=DURATION_BUCKETS,
)


def observe_queue_depth(options: CallbackOptions) -> Iterable[Observation]:
    """Report how many claimable units this process last saw."""
    return [Observation(gauges.queue_depth)]


def observe_waiting(options: CallbackOptions) -> Iterable[Observation]:
    """Report how many attempts this process last saw parked rather than running."""
    return [Observation(gauges.waiting)]


def observe_in_flight(options: CallbackOptions) -> Iterable[Observation]:
    """Report how many block calls this worker is running right now.

    A process with no worker in it reports nothing rather than a zero under no name.
    """
    if gauges.worker is None:
        return []
    return [Observation(gauges.in_flight, {"dirigent.worker": gauges.worker})]


def observe_scheduler_lag(options: CallbackOptions) -> Iterable[Observation]:
    """Report how late the oldest due schedule was at this process's last tick."""
    return [Observation(gauges.scheduler_lag)]


def observe_heartbeat_age(options: CallbackOptions) -> Iterable[Observation]:
    """Report how long ago each registered worker last reported in."""
    return [Observation(age, {"dirigent.worker": name}) for name, age in gauges.heartbeat_ages.items()]


def register_instruments() -> None:
    """Rebuild the instruments against the configured meter, once the SDK is installed."""
    global _runs, _steps, _step_duration, _block_duration
    _runs = _meter.create_counter("dirigent.runs", description="Runs by terminal status.")
    _steps = _meter.create_counter("dirigent.steps", description="Step attempts by terminal status.")
    _step_duration = _meter.create_histogram(
        "dirigent.step.duration",
        unit="s",
        description="How long a step attempt took.",
        explicit_bucket_boundaries_advisory=DURATION_BUCKETS,
    )
    _block_duration = _meter.create_histogram(
        "dirigent.block.duration",
        unit="s",
        description="How long one block call took.",
        explicit_bucket_boundaries_advisory=DURATION_BUCKETS,
    )
    _meter.create_observable_gauge(
        "dirigent.queue.depth", callbacks=[observe_queue_depth], description="Claimable units of work."
    )
    _meter.create_observable_gauge(
        "dirigent.waiting", callbacks=[observe_waiting], description="Attempts parked, not running on a worker."
    )
    _meter.create_observable_gauge(
        "dirigent.worker.in_flight", callbacks=[observe_in_flight], description="Block calls running now."
    )
    _meter.create_observable_gauge(
        "dirigent.scheduler.lag",
        unit="s",
        callbacks=[observe_scheduler_lag],
        description="Seconds between the oldest due schedule's due time and the tick that fires it.",
    )
    _meter.create_observable_gauge(
        "dirigent.worker.heartbeat_age",
        unit="s",
        callbacks=[observe_heartbeat_age],
        description="Seconds since each registered worker last reported in.",
    )


def record_run(status: str, pipeline: str) -> None:
    """Count one run reaching a terminal status."""
    _runs.add(1, {"dirigent.run.status": status, "dirigent.pipeline": pipeline})


def record_step(status: str, block: str, seconds: float | None = None) -> None:
    """Count one step attempt settling, and how long it took."""
    attributes = {"dirigent.step.status": status, "dirigent.block": block}
    _steps.add(1, attributes)
    if seconds is not None:
        _step_duration.record(seconds, attributes)


def record_block_call(block: str, call: str, seconds: float) -> None:
    """Record how long one block call took."""
    _block_duration.record(seconds, {"dirigent.block": block, "dirigent.block.call": call})


@contextmanager
def run_span(pipeline: str, *, trigger: str | None = None) -> Generator[Span]:
    """Open the root span of a run: creating it, and the parent of every attempt of it.

    The span covers the creation, not the run. A run outlives the process that started it
    and executes on workers that were not there yet, so what joins them is the traceparent
    this span is captured as. Its children therefore end long after it does.
    """
    with _tracer.start_as_current_span(
        f"run {pipeline}",
        kind=SpanKind.PRODUCER,
        attributes={"dirigent.pipeline": pipeline, "dirigent.run.trigger": trigger or "unknown"},
    ) as span:
        yield span


@contextmanager
def attempt_span(*, run_id: str, step: str, block: str, attempt: int, parent: Context | None = None) -> Generator[Span]:
    """Open the span covering one step attempt, from claim to settled outcome.

    ``parent`` is the run's own trace context, read back from the run row, which is what
    puts an attempt run on a worker into the trace of whatever asked for the run.
    """
    with _tracer.start_as_current_span(
        f"step {step}",
        context=parent,
        kind=SpanKind.CONSUMER,
        attributes={
            "dirigent.run.id": run_id,
            "dirigent.step": step,
            "dirigent.block": block,
            "dirigent.attempt": attempt,
        },
    ) as span:
        yield span


@contextmanager
def block_span(block: str, call: str) -> Generator[Span]:
    """Open the span covering one block call: execute, probe, fetch, or cancel."""
    with _tracer.start_as_current_span(
        f"{block}.{call}",
        kind=SpanKind.CLIENT,
        attributes={"dirigent.block": block, "dirigent.block.call": call},
    ) as span:
        yield span


def record_failure(span: Span, error: BaseException | str) -> None:
    """Mark a span as failed, with the message an operator would want in the trace."""
    if isinstance(error, BaseException):
        span.record_exception(error)
        span.set_status(Status(StatusCode.ERROR, str(error)))
    else:
        span.set_status(Status(StatusCode.ERROR, error))


def current_traceparent() -> str | None:
    """Write the active span down as a W3C traceparent, for a run row to carry.

    Returns nothing when no exporter is configured, because the no-op span's all-zero ids
    name a trace that does not exist and would parent every attempt onto nothing.
    """
    carrier: dict[str, str] = {}
    _propagator.inject(carrier)
    return carrier.get("traceparent")


def context_from(traceparent: str | None) -> Context | None:
    """Read a stored traceparent back into a context a span can be opened under."""
    if not traceparent:
        return None
    context = _propagator.extract({"traceparent": traceparent})
    return context if trace.get_current_span(context).get_span_context().is_valid else None


def trace_id_of(traceparent: str | None) -> str | None:
    """Read the trace out of a traceparent, which is what deep-links to a trace viewer.

    A context that does not read back names no trace, all-zero ids included: they would
    deep-link to a trace that does not exist.
    """
    context = context_from(traceparent)
    if context is None:
        return None
    return format(trace.get_current_span(context).get_span_context().trace_id, "032x")


def instrument_fastapi(app: Any) -> None:
    """Give every HTTP request a span, without depending on an instrumentation package."""

    async def span_per_request(request: Any, call_next: Callable[[Any], Any]) -> Any:
        """Wrap one request in a span named after its route.

        The span is named and attributed from a redacted path, never the raw one: a delivery
        to ``POST /hooks/<token>`` carries its whole credential in the path, and a span name
        travels to every trace viewer the operator has.
        """
        path = redact_path(request.url.path)
        with _tracer.start_as_current_span(
            f"{request.method} {path}",
            kind=SpanKind.SERVER,
            attributes={"http.request.method": request.method, "url.path": path},
        ) as span:
            response = await call_next(request)
            template = getattr(request.scope.get("route"), "path", None)
            if isinstance(template, str):
                span.set_attribute("http.route", template)
                span.update_name(f"{request.method} {template}")
            span.set_attribute("http.response.status_code", response.status_code)
            if response.status_code >= 500:
                record_failure(span, f"HTTP {response.status_code}")
            return response

    app.middleware("http")(span_per_request)
