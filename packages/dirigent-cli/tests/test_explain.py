"""What a document will cost before it runs, read off the document and the catalog alone."""

from datetime import timedelta
from typing import Any

from dirigent_cli.explain import explain
from dirigent_client.schemas import BlockEntry, BlockKind, Catalog
from dirigent_core.engine.definition import PipelineDefinition


def document(steps: dict[str, Any], params: dict[str, Any] | None = None) -> PipelineDefinition:
    """A pipeline document with these steps, and the parameter schema it reads."""
    body: dict[str, Any] = {"format": "dirigent/v1", "kind": "pipeline", "code": "demo", "steps": steps}
    if params is not None:
        body["params"] = params
    return PipelineDefinition.model_validate(body)


def rows(shape: Any) -> dict[str, Any]:
    """The steps of a shape, keyed by the step they describe."""
    return {row.step: row for row in shape.steps}


def sensor_catalog(*, poll: float | None = 30.0, deadline: float | None = 600.0) -> Catalog:
    """A catalog whose one sensor declares these defaults."""
    return Catalog(
        blocks=[
            BlockEntry(
                id="time.wait",
                kind=BlockKind.SENSOR,
                summary="Wait for a moment to pass.",
                group="time",
                plugin="dirigent-blocks",
                default_poll_seconds=poll,
                default_deadline_seconds=deadline,
            )
        ]
    )


def test_a_step_that_does_not_fan_out_is_one_item() -> None:
    shape = explain(document({"one": {"block": "shell.run"}}))
    assert rows(shape)["one"].cardinality == 1
    assert rows(shape)["one"].elements == 1
    assert shape.attempts_max == 1
    assert shape.attempts_at_least is False


def test_a_literal_list_is_its_own_length() -> None:
    shape = explain(document({"one": {"block": "shell.run", "for_each": ["a", "b", "c"]}}))
    assert rows(shape)["one"].cardinality == 3
    assert rows(shape)["one"].reference is None


def test_a_parameter_with_a_default_fixes_the_cardinality() -> None:
    shape = explain(
        document(
            {"one": {"block": "shell.run", "for_each": "${params.regions}"}},
            {"type": "object", "properties": {"regions": {"type": "array", "default": ["east", "west"]}}},
        )
    )
    assert rows(shape)["one"].cardinality == 2
    assert rows(shape)["one"].reference == "${params.regions}"


def test_a_parameter_with_no_default_is_unknown_and_names_the_reference() -> None:
    """Only the run supplies it, so the shape says so rather than guessing a width."""
    shape = explain(
        document(
            {"one": {"block": "shell.run", "for_each": "${params.regions}"}},
            {"type": "object", "properties": {"regions": {"type": "array"}}},
        )
    )
    assert rows(shape)["one"].cardinality == "unknown"
    assert rows(shape)["one"].elements is None
    assert rows(shape)["one"].reference == "${params.regions}"
    assert shape.attempts_at_least is True


def test_a_parameter_the_document_requires_leaves_every_cardinality_unknown() -> None:
    """A schema with no defaults to fill raises rather than resolving, and that is not an error."""
    shape = explain(
        document(
            {"one": {"block": "shell.run", "for_each": "${params.regions}"}},
            {
                "type": "object",
                "properties": {"regions": {"type": "array"}},
                "required": ["regions"],
            },
        )
    )
    assert rows(shape)["one"].cardinality == "unknown"


def test_a_reference_that_is_not_a_list_is_unknown() -> None:
    shape = explain(
        document(
            {"one": {"block": "shell.run", "for_each": "${params.width}"}},
            {"type": "object", "properties": {"width": {"type": "integer", "default": 4}}},
        )
    )
    assert rows(shape)["one"].cardinality == "unknown"
    assert rows(shape)["one"].elements is None


def test_an_adoption_names_the_grid_it_maps_over_and_carries_its_count() -> None:
    shape = explain(
        document(
            {
                "wide": {"block": "shell.run", "for_each": ["a", "b", "c"]},
                "each": {
                    "block": "shell.run",
                    "depends_on": ["wide"],
                    "for_each": "${steps.wide.items}",
                },
            }
        )
    )
    assert rows(shape)["each"].cardinality == "adopts wide"
    assert rows(shape)["each"].elements == 3
    assert shape.attempts_max == 6


def test_an_adoption_chain_carries_the_count_through_every_link() -> None:
    shape = explain(
        document(
            {
                "wide": {"block": "shell.run", "for_each": ["a", "b"]},
                "middle": {"block": "shell.run", "depends_on": ["wide"], "for_each": "${steps.wide.items}"},
                "last": {"block": "shell.run", "depends_on": ["middle"], "for_each": "${steps.middle.items}"},
            }
        )
    )
    assert rows(shape)["last"].cardinality == "adopts middle"
    assert rows(shape)["last"].elements == 2
    assert shape.attempts_max == 6


def test_an_adoption_of_an_unknown_grid_stays_unknown() -> None:
    shape = explain(
        document(
            {
                "wide": {"block": "shell.run", "for_each": "${params.regions}"},
                "each": {"block": "shell.run", "depends_on": ["wide"], "for_each": "${steps.wide.items}"},
            },
            {"type": "object", "properties": {"regions": {"type": "array"}}},
        )
    )
    assert rows(shape)["each"].cardinality == "adopts wide"
    assert rows(shape)["each"].elements is None
    assert shape.attempts_at_least is True


def test_a_for_each_reading_a_step_output_is_unknown() -> None:
    """resolve_fan_out refuses it when the run is created; the shape cannot resolve it either."""
    shape = explain(
        document(
            {
                "first": {"block": "shell.run"},
                "second": {"block": "shell.run", "depends_on": ["first"], "for_each": "${steps.first.output}"},
            }
        )
    )
    assert rows(shape)["second"].cardinality == "unknown"


def test_an_unknown_cardinality_counts_once_and_marks_the_total_a_floor() -> None:
    shape = explain(
        document(
            {
                "one": {"block": "shell.run", "for_each": "${params.regions}", "retry": {"max_attempts": 3}},
                "two": {"block": "shell.run", "depends_on": ["one"]},
            },
            {"type": "object", "properties": {"regions": {"type": "array"}}},
        )
    )
    assert shape.attempts_max == 4
    assert shape.attempts_at_least is True


def test_the_retry_wait_adds_every_backoff_the_policy_allows() -> None:
    """Three attempts have two delays between them: the first, and the first multiplied."""
    shape = explain(
        document(
            {
                "one": {
                    "block": "shell.run",
                    "retry": {"max_attempts": 3, "backoff": "30s", "multiplier": 2.0, "jitter": 0.0},
                }
            }
        )
    )
    assert rows(shape)["one"].retry_wait == timedelta(seconds=90)


def test_the_retry_wait_is_nothing_where_there_is_only_one_attempt() -> None:
    shape = explain(document({"one": {"block": "shell.run"}}))
    assert rows(shape)["one"].retry_wait is None
    assert rows(shape)["one"].max_attempts == 1


def test_the_retry_wait_is_capped_by_max_backoff() -> None:
    shape = explain(
        document(
            {
                "one": {
                    "block": "shell.run",
                    "retry": {
                        "max_attempts": 4,
                        "backoff": "1m",
                        "multiplier": 10.0,
                        "max_backoff": "2m",
                        "jitter": 0.0,
                    },
                }
            }
        )
    )
    assert rows(shape)["one"].retry_wait == timedelta(minutes=5)


def test_the_retry_wait_is_the_top_of_the_jitter_the_policy_spreads_over() -> None:
    """The worst case is what a budget is read for, and jitter's worst case is its whole spread."""
    shape = explain(
        document(
            {
                "one": {
                    "block": "shell.run",
                    "retry": {"max_attempts": 2, "backoff": "30s", "jitter": 0.2},
                }
            }
        )
    )
    assert rows(shape)["one"].retry_wait == timedelta(seconds=36)


def test_the_longest_deadline_chain_follows_the_dag_rather_than_the_document_order() -> None:
    shape = explain(
        document(
            {
                "quick": {"block": "time.wait", "deadline": "1m"},
                "slow": {"block": "time.wait", "deadline": "10m"},
                "after_slow": {"block": "time.wait", "depends_on": ["slow"], "deadline": "5m"},
                "after_quick": {"block": "time.wait", "depends_on": ["quick"], "deadline": "2m"},
            }
        )
    )
    assert shape.deadline_longest == timedelta(minutes=15)


def test_a_document_with_no_deadline_anywhere_has_no_chain() -> None:
    shape = explain(document({"one": {"block": "shell.run"}}))
    assert shape.deadline_longest is None


def test_a_fan_out_only_the_run_can_size_is_warned_about_by_name() -> None:
    shape = explain(
        document(
            {"one": {"block": "shell.run", "for_each": "${params.regions}"}},
            {"type": "object", "properties": {"regions": {"type": "array"}}},
        )
    )
    warning = shape.warnings[0]
    assert warning.cause == "unknown-cardinality"
    assert warning.step == "one"
    assert "${params.regions}" in warning.message


def test_a_retry_budget_longer_than_the_deadline_is_warned_about() -> None:
    shape = explain(
        document(
            {
                "one": {
                    "block": "time.wait",
                    "deadline": "1m",
                    "retry": {"max_attempts": 3, "backoff": "1m", "jitter": 0.0},
                }
            }
        )
    )
    causes = [one.cause for one in shape.warnings]
    assert "retry-outlasts-deadline" in causes
    assert "3m" in next(one.message for one in shape.warnings if one.cause == "retry-outlasts-deadline")


def test_a_retry_budget_inside_the_deadline_is_not_warned_about() -> None:
    shape = explain(
        document(
            {
                "one": {
                    "block": "time.wait",
                    "deadline": "10m",
                    "retry": {"max_attempts": 3, "backoff": "1m", "jitter": 0.0},
                }
            }
        )
    )
    assert shape.warnings == []


def test_a_sensor_with_no_deadline_is_warned_about_offline_by_its_cadence() -> None:
    """Offline the only thing that says a step waits on a sensor is the cadence it declares."""
    shape = explain(document({"one": {"block": "time.wait", "poll": "30s"}}))
    assert [one.cause for one in shape.warnings] == ["unbounded-sensor"]
    assert "--server" in shape.warnings[0].message


def test_a_sensor_the_catalog_bounds_is_not_warned_about() -> None:
    shape = explain(document({"one": {"block": "time.wait"}}), sensor_catalog())
    assert shape.warnings == []


def test_the_catalog_fills_a_sensor_wait_the_document_left_out_and_the_row_says_so() -> None:
    shape = explain(document({"one": {"block": "time.wait"}}), sensor_catalog())
    row = rows(shape)["one"]
    assert row.poll == timedelta(seconds=30)
    assert row.deadline == timedelta(minutes=10)
    assert row.from_block == ["poll", "deadline"]
    assert shape.deadline_longest == timedelta(minutes=10)


def test_the_document_keeps_what_it_declared_over_the_block_default() -> None:
    shape = explain(document({"one": {"block": "time.wait", "poll": "5s", "deadline": "1m"}}), sensor_catalog())
    row = rows(shape)["one"]
    assert (row.poll, row.deadline) == (timedelta(seconds=5), timedelta(minutes=1))
    assert row.from_block == []


def test_a_sensor_the_catalog_bounds_with_nothing_is_warned_about() -> None:
    shape = explain(document({"one": {"block": "time.wait"}}), sensor_catalog(deadline=None))
    assert [one.cause for one in shape.warnings] == ["unbounded-sensor"]
    assert "--server" not in shape.warnings[0].message


def test_an_operator_with_no_deadline_is_not_a_sensor_and_is_not_warned_about() -> None:
    catalog = Catalog(
        blocks=[
            BlockEntry(
                id="shell.run",
                kind=BlockKind.OPERATOR,
                summary="Run a command.",
                group="shell",
                plugin="dirigent-blocks",
            )
        ]
    )
    assert explain(document({"one": {"block": "shell.run"}}), catalog).warnings == []


def test_a_block_the_catalog_has_never_heard_of_keeps_the_document_values() -> None:
    shape = explain(document({"one": {"block": "shell.run", "poll": "5s"}}), sensor_catalog())
    assert rows(shape)["one"].poll == timedelta(seconds=5)
    assert rows(shape)["one"].from_block == []


def test_the_steps_are_read_in_the_order_they_will_run() -> None:
    shape = explain(
        document(
            {
                "last": {"block": "shell.run", "depends_on": ["first"]},
                "first": {"block": "shell.run"},
            }
        )
    )
    assert [row.step for row in shape.steps] == ["first", "last"]
    assert rows(shape)["last"].depends_on == ["first"]
