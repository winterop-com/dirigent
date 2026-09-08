"""Telemetry: a complete no-op until an exporter is configured, and real when one is."""

import os
import socket
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.metrics import CallbackOptions
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import Histogram, InMemoryMetricReader

from dirigent_core import telemetry
from dirigent_core.config import Settings


@pytest.fixture(autouse=True)
def _forget_configuration() -> Any:  # pyright: ignore[reportUnusedFunction]
    """Leave the module unconfigured, so one test cannot install an SDK for another."""
    telemetry.reset_telemetry()
    yield
    telemetry.reset_telemetry()


def test_nothing_is_configured_when_the_environment_names_no_exporter() -> None:
    assert telemetry.exporter_configured({}) is False
    assert telemetry.configure_telemetry(Settings(), environ={}) is False


@pytest.mark.parametrize(
    "environ",
    [
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318"},
        {"OTEL_TRACES_EXPORTER": "console"},
        {"OTEL_METRICS_EXPORTER": "console"},
        {"OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://localhost:4318/v1/traces"},
    ],
)
def test_an_exporter_in_the_environment_is_recognised(environ: dict[str, str]) -> None:
    assert telemetry.exporter_configured(environ) is True


@pytest.mark.parametrize(
    "environ",
    [
        {"OTEL_TRACES_EXPORTER": "none"},
        {"OTEL_TRACES_EXPORTER": ""},
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318", "OTEL_SDK_DISABLED": "true"},
    ],
)
def test_the_standard_ways_of_saying_off_are_honoured(environ: dict[str, str]) -> None:
    assert telemetry.exporter_configured(environ) is False


def test_every_span_and_metric_works_with_nothing_configured() -> None:
    with (
        telemetry.run_span("demo", trigger="adhoc"),
        telemetry.attempt_span(run_id="r", step="s", block="test.echo", attempt=1) as span,
    ):
        with telemetry.block_span("test.echo", "execute"):
            telemetry.record_block_call("test.echo", "execute", 0.01)
        telemetry.record_failure(span, "something went wrong")
        telemetry.record_failure(span, ValueError("or an exception"))
    telemetry.record_run("succeeded", "demo")
    telemetry.record_step("succeeded", "test.echo", 0.5)
    telemetry.record_step("failed", "test.echo")


def test_there_is_no_trace_context_to_carry_when_nothing_is_configured() -> None:
    """A no-op span's all-zero ids name a trace that does not exist."""
    with telemetry.run_span("demo"):
        assert telemetry.current_traceparent() is None


def test_the_gauges_report_what_the_engine_last_saw() -> None:
    telemetry.gauges.observe(queue_depth=7, waiting=3, scheduler_lag=12.5, heartbeat_ages={"worker-a": 4.0})
    assert telemetry.gauges.queue_depth == 7
    assert telemetry.gauges.waiting == 3
    assert telemetry.gauges.scheduler_lag == 12.5
    assert telemetry.gauges.heartbeat_ages == {"worker-a": 4.0}
    telemetry.gauges.observe(queue_depth=0)
    assert telemetry.gauges.queue_depth == 0
    assert telemetry.gauges.waiting == 3
    assert telemetry.gauges.scheduler_lag == 12.5
    options = CallbackOptions()
    assert list(telemetry.observe_queue_depth(options))[0].value == 0
    assert list(telemetry.observe_waiting(options))[0].value == 3
    telemetry.gauges.worker = "worker-a"
    telemetry.gauges.in_flight = 2
    assert [(one.value, one.attributes) for one in telemetry.observe_in_flight(options)] == [
        (2, {"dirigent.worker": "worker-a"})
    ]
    telemetry.gauges.worker = None
    assert list(telemetry.observe_in_flight(options)) == []
    assert list(telemetry.observe_scheduler_lag(options))[0].value == 12.5
    heartbeats = list(telemetry.observe_heartbeat_age(options))
    assert [(one.value, one.attributes) for one in heartbeats] == [(4.0, {"dirigent.worker": "worker-a"})]
    telemetry.gauges.observe(heartbeat_ages={})
    assert list(telemetry.observe_heartbeat_age(options)) == []


def test_the_duration_histograms_carry_their_own_bucket_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    """The SDK's defaults start at 0, 5, 10, which is one bucket for every step worth timing."""
    reader = InMemoryMetricReader()
    monkeypatch.setattr(telemetry, "_meter", MeterProvider(metric_readers=[reader]).get_meter(telemetry.SCOPE))
    telemetry.register_instruments()

    telemetry.record_step("succeeded", "test.echo", 0.04)
    telemetry.record_block_call("test.echo", "execute", 3.0)

    collected = reader.get_metrics_data()
    assert collected is not None
    bounds: dict[str, tuple[float, ...]] = {}
    for resource in collected.resource_metrics:
        for scope in resource.scope_metrics:
            for metric in scope.metrics:
                if isinstance(metric.data, Histogram):
                    bounds[metric.name] = tuple(metric.data.data_points[0].explicit_bounds)
    assert bounds == {
        "dirigent.step.duration": telemetry.DURATION_BUCKETS,
        "dirigent.block.duration": telemetry.DURATION_BUCKETS,
    }
    assert telemetry.DURATION_BUCKETS[0] == 0.005
    assert telemetry.DURATION_BUCKETS[-1] == 900.0


def test_the_resource_names_the_process_instance_unless_the_environment_did() -> None:
    """Two workers of one service collide in a metrics backend without an instance id."""
    attributes = telemetry.resource_attributes(Settings(), {})
    assert attributes["service.instance.id"] == f"{socket.gethostname()}-{os.getpid()}"
    assert attributes["service.name"] == "dirigent"

    named = telemetry.resource_attributes(
        Settings(), {"OTEL_RESOURCE_ATTRIBUTES": "host.name=box,service.instance.id=worker-7"}
    )
    assert "service.instance.id" not in named


def test_configuring_the_sdk_makes_spans_real_and_gives_a_run_a_trace_context() -> None:
    configured = telemetry.configure_telemetry(
        Settings(),
        environ={
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
            "OTEL_TRACES_EXPORTER": "none",
            "OTEL_METRICS_EXPORTER": "none",
        },
    )
    assert configured is True
    with telemetry.run_span("demo"):
        traceparent = telemetry.current_traceparent()
    trace_id = telemetry.trace_id_of(traceparent)
    assert trace_id is not None
    assert len(trace_id) == 32
    assert int(trace_id, 16) != 0


def test_a_broken_exporter_is_a_warning_not_a_failed_start(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_: object, **__: object) -> None:
        raise RuntimeError("the collector is not there")

    monkeypatch.setattr(telemetry, "_install_sdk", explode)
    assert telemetry.configure_telemetry(Settings(), environ={"OTEL_TRACES_EXPORTER": "console"}) is False


def test_a_stored_trace_context_reads_back_as_the_span_to_hang_work_from() -> None:
    """This is the whole propagation: a column in, a parent context out."""
    stored = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"

    context = telemetry.context_from(stored)

    assert context is not None
    assert telemetry.trace_id_of(stored) == "4bf92f3577b34da6a3ce929d0e0e4736"
    span_context = trace.get_current_span(context).get_span_context()
    assert format(span_context.trace_id, "032x") == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert format(span_context.span_id, "016x") == "00f067aa0ba902b7"


@pytest.mark.parametrize(
    "stored",
    [None, "", "not a traceparent", "00-00000000000000000000000000000000-0000000000000000-01"],
)
def test_a_trace_context_that_is_not_one_parents_nothing(stored: str | None) -> None:
    """A worker never opens a span under a context it could not read."""
    assert telemetry.context_from(stored) is None
    assert telemetry.trace_id_of(stored) is None
