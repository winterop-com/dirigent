"""Tests for ``playground.generate``: the node at the start, in the middle, and at the end."""

from typing import Any

import pytest
from pydantic import ValidationError

from dirigent_block_base.playground import (
    Drift,
    PlaygroundOperator,
    PlaygroundOutput,
    PlaygroundRefusal,
    locales,
    providers,
)
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block


async def generate(ctx: FakeContext, **config: object) -> PlaygroundOutput:
    """Run the node once and hand back its output, typed."""
    output = await call_block(PlaygroundOperator(), config, ctx)
    assert isinstance(output, PlaygroundOutput)
    return output


def record(output: PlaygroundOutput, index: int = 0) -> dict[str, Any]:
    """One record of an output, as the mapping every generated record is."""
    found = output.records[index]
    assert isinstance(found, dict)
    return found


async def test_a_first_step_needs_no_input_and_no_knobs(ctx: FakeContext) -> None:
    """The lead case: a document's first step, with nothing upstream and nothing configured."""
    output = await generate(ctx)
    assert output.rows == 1
    assert len(output.records) == 1
    assert set(record(output)) == {"name", "email", "city"}
    assert output.input_rows is None


async def test_a_seed_makes_the_rows_reproducible(ctx: FakeContext) -> None:
    first = await generate(ctx, rows=5, seed=17, fields={"who": "name"})
    second = await generate(ctx, rows=5, seed=17, fields={"who": "name"})
    assert first.records == second.records
    assert first.seed == 17


async def test_an_unseeded_run_says_which_seed_it_drew(ctx: FakeContext) -> None:
    """A surprising answer has to be reproducible, so the drawn seed is on the output."""
    output = await generate(ctx, rows=2, fields={"who": "name"})
    repeated = await generate(ctx, rows=2, seed=output.seed, fields={"who": "name"})
    assert repeated.records == output.records


async def test_the_field_map_reaches_any_provider(ctx: FakeContext) -> None:
    output = await generate(ctx, rows=1, seed=1, fields={"when": "date_this_decade", "what": "catch_phrase"})
    assert set(record(output)) == {"when", "what"}


async def test_a_provider_takes_its_own_arguments(ctx: FakeContext) -> None:
    output = await generate(
        ctx,
        rows=4,
        seed=3,
        fields={"score": {"provider": "pyint", "args": {"min_value": 10, "max_value": 12}}},
    )
    assert all(10 <= record(output, index)["score"] <= 12 for index in range(4))


async def test_a_provider_that_is_not_one_is_refused(ctx: FakeContext) -> None:
    with pytest.raises(PlaygroundRefusal) as raised:
        await generate(ctx, fields={"x": "not_a_provider"})
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "not_a_provider" in str(raised.value)


async def test_an_attribute_that_is_not_a_provider_is_refused(ctx: FakeContext) -> None:
    """A field map is a string selecting an attribute, so it is bounded to real providers."""
    for name in ("seed_instance", "__class__", "_factory_map", "add_provider"):
        with pytest.raises(PlaygroundRefusal):
            await generate(ctx, fields={"x": name})


async def test_a_locale_that_is_not_shipped_is_refused(ctx: FakeContext) -> None:
    with pytest.raises(PlaygroundRefusal) as raised:
        await generate(ctx, locale="xx_XX")
    assert "xx_XX" in str(raised.value)


async def test_another_locale_generates_in_that_locale(ctx: FakeContext) -> None:
    output = await generate(ctx, rows=3, seed=5, locale="no_NO", fields={"where": "city"})
    assert output.locale == "no_NO"
    assert len(output.records) == 3


@pytest.mark.parametrize(
    ("drift", "expected"),
    [
        (Drift.STRINGS, "strings"),
        (Drift.MISSING, "missing"),
        (Drift.EXTRA, "extra"),
    ],
)
async def test_each_drift_breaks_a_different_rule(ctx: FakeContext, drift: Drift, expected: str) -> None:
    fields = {"count": {"provider": "pyint", "args": {"min_value": 1, "max_value": 9}}, "who": "name"}
    output = await generate(ctx, rows=2, seed=2, fields=fields, drift=expected)
    first = record(output)
    assert output.drift is drift
    match drift:
        case Drift.STRINGS:
            assert isinstance(first["count"], str)
        case Drift.MISSING:
            assert "count" not in first
        case Drift.EXTRA:
            assert first["drifted"] is True
        case Drift.NONE:  # pragma: no cover - the parametrisation never passes it
            raise AssertionError("no drift is not one of the drifts under test")


async def test_a_page_is_a_slice_of_the_rows(ctx: FakeContext) -> None:
    output = await generate(ctx, rows=25, seed=9, size=10, page=3, fields={"who": "name"})
    assert output.rows == 25
    assert output.pages == 3
    assert len(output.records) == 5


async def test_a_payload_pushes_the_output_over_a_threshold(ctx: FakeContext) -> None:
    output = await generate(ctx, rows=0, payload="32kb")
    assert output.payload_bytes == 32 * 1024
    assert output.payload is not None
    assert len(output.payload) == 32 * 1024


async def test_the_payload_is_the_same_bytes_every_run(ctx: FakeContext) -> None:
    first = await generate(ctx, rows=0, payload="1kb")
    second = await generate(ctx, rows=0, payload="1kb", seed=99)
    assert first.payload == second.payload


async def test_failing_attempts_fail_and_then_succeed(ctx: FakeContext) -> None:
    """A retry example proves a retry: the first attempts fail transiently, the next succeeds."""
    ctx.attempt = 1
    with pytest.raises(BlockFailure) as raised:
        await generate(ctx, fail_until=2)
    assert raised.value.error_class is ErrorClass.TRANSIENT

    ctx.attempt = 2
    with pytest.raises(BlockFailure):
        await generate(ctx, fail_until=2)

    ctx.attempt = 3
    output = await generate(ctx, fail_until=2)
    assert output.attempt == 3
    assert output.fail_until == 2


async def test_a_delay_is_reported_in_milliseconds(ctx: FakeContext) -> None:
    output = await generate(ctx, rows=0, delay="50ms")
    assert output.delay_ms == 50


async def test_a_list_input_passes_through_when_no_fields_are_named(ctx: FakeContext) -> None:
    """In the middle of a document: the input decides how many records there are."""
    supplied = [{"code": "a"}, {"code": "b"}, {"code": "c"}]
    output = await generate(ctx, input=supplied, rows=10)
    assert output.records == supplied
    assert output.rows == 3
    assert output.input_rows == 3


async def test_named_fields_are_added_to_a_supplied_input(ctx: FakeContext) -> None:
    output = await generate(ctx, input=[{"code": "a"}], seed=4, fields={"who": "name"})
    assert record(output)["code"] == "a"
    assert "who" in record(output)


async def test_a_scalar_input_becomes_one_record(ctx: FakeContext) -> None:
    output = await generate(ctx, input=7, fields={"who": "name"})
    assert record(output)["value"] == 7
    assert output.input_rows == 1


async def test_a_supplied_input_can_be_drifted_and_paged(ctx: FakeContext) -> None:
    supplied = [{"count": index} for index in range(12)]
    output = await generate(ctx, input=supplied, drift="strings", page=2, size=5)
    assert output.rows == 12
    assert output.pages == 3
    assert record(output)["count"] == "5"


async def test_the_node_is_useful_as_a_last_step(ctx: FakeContext) -> None:
    """At the end of a document: it requires nothing downstream and its output stands alone."""
    output = await generate(ctx, input=[{"code": "a"}], payload="256b")
    assert output.records == [{"code": "a"}]
    assert output.payload_bytes == 256


async def test_the_output_repeats_the_knobs_that_produced_it(ctx: FakeContext) -> None:
    output = await generate(ctx, rows=2, seed=11, locale="fr_FR", fields={"who": "name"}, drift="extra")
    assert output.seed == 11
    assert output.locale == "fr_FR"
    assert output.fields == {"who": "name"}
    assert output.drift is Drift.EXTRA


async def test_the_config_schema_refuses_a_key_it_does_not_know() -> None:
    schema = PlaygroundOperator.config_model.model_json_schema(mode="serialization")
    assert schema["additionalProperties"] is False


async def test_too_many_rows_is_refused(ctx: FakeContext) -> None:
    with pytest.raises(ValidationError):
        await generate(ctx, rows=100_000)


async def test_too_long_a_delay_is_refused(ctx: FakeContext) -> None:
    with pytest.raises(ValidationError):
        await generate(ctx, delay="10m")


def test_the_provider_list_is_what_a_field_map_may_name() -> None:
    """A reader cannot guess 280 provider names, so the installed Faker is asked for them."""
    found = providers()
    assert "name" in found.providers
    assert found.locale == "en_US"
    assert not any(name.startswith("_") for name in found.providers)
    assert not {"seed", "seed_instance", "add_provider", "format"} & set(found.providers)


def test_the_provider_list_answers_per_locale() -> None:
    assert providers("no_NO").locale == "no_NO"
    with pytest.raises(PlaygroundRefusal):
        providers("xx_XX")


def test_every_locale_faker_ships_is_offered() -> None:
    assert "en_US" in locales()
    assert locales() == sorted(locales())


async def test_the_block_is_in_the_catalog() -> None:
    assert PlaygroundOperator.spec.id == "playground.generate"
    assert PlaygroundOperator.spec.group == "playground"
