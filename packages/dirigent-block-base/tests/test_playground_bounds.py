"""What one generation may reach and spend: the providers it names, and those they dispatch to."""

import asyncio
import threading
import time
from datetime import timedelta

import pytest
from faker.generator import Generator

from dirigent_block_base import playground
from dirigent_block_base.playground import Generation, PlaygroundOperator, PlaygroundRefusal, generate, providers
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, call_block


def one(spec: object) -> Generation:
    """Knobs generating one record of one field."""
    return Generation.model_validate({"fields": {"x": spec}})


@pytest.mark.parametrize(
    "spec",
    [
        {"provider": "pystr_format", "args": {"string_format": "{{seed}}"}},
        {"provider": "pystr_format", "args": {"string_format": "{{seed_instance}}"}},
        {"provider": "json", "args": {"data_columns": {"a": "seed"}, "num_rows": 1}},
        {"provider": "json", "args": {"data_columns": {"a": "{{seed}}"}, "num_rows": 1}},
        {"provider": "csv", "args": {"data_columns": ["{{seed}}"], "num_rows": 1}},
        {"provider": "pylist", "args": {"nb_elements": 1, "value_types": ["seed"]}},
    ],
)
def test_a_provider_cannot_dispatch_to_a_name_outside_the_allowlist(spec: object) -> None:
    before = Generator._is_seeded  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(PlaygroundRefusal, match="not a provider"):
        generate(one(spec), 1)
    assert Generator._is_seeded == before, "the class-wide seed is untouched"  # pyright: ignore[reportPrivateUsage]


def test_a_provider_may_dispatch_to_a_name_on_the_allowlist() -> None:
    spec = {"provider": "json", "args": {"data_columns": {"a": "name", "b": "{{city}}"}, "num_rows": 1}}
    [record] = generate(one(spec), 1)
    assert isinstance(record, dict)
    assert '"a"' in str(record["x"])


@pytest.mark.parametrize(
    "spec",
    [
        {"provider": "pystr", "args": {"max_chars": 10_001}},
        {"provider": "binary", "args": {"length": 10_001}},
        {"provider": "paragraphs", "args": {"nb": 10_001}},
        {"provider": "json", "args": {"data_columns": {"a": ["pystr", {"max_chars": 10_001}]}, "num_rows": 1}},
        {"provider": "json", "args": {"data_columns": {"a": "name"}, "num_rows": 10_001}},
    ],
)
def test_an_argument_naming_a_size_past_the_limit_is_refused(spec: object) -> None:
    with pytest.raises(PlaygroundRefusal, match="past"):
        generate(one(spec), 1)


def test_an_argument_naming_a_value_takes_any_number() -> None:
    [record] = generate(one({"provider": "pyint", "args": {"min_value": 10**12, "max_value": 10**12}}), 1)
    assert isinstance(record, dict)
    assert record["x"] == 10**12


def test_every_provider_an_instance_lists_still_runs_with_no_arguments() -> None:
    """What a provider dispatches to on its own is never what the allowlist refuses."""
    refused: list[str] = []
    for name in providers().providers:
        try:
            generate(one(name), 1)
        except PlaygroundRefusal as error:
            if "not a provider" in str(error) or "past" in str(error):
                refused.append(name)
    assert refused == []


def test_a_field_map_as_wide_as_it_likes_is_bound_by_the_calls_it_makes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(playground, "MAX_PROVIDER_CALLS", 50)
    knobs = Generation.model_validate({"fields": {f"f{index}": "name" for index in range(60)}})
    with pytest.raises(PlaygroundRefusal) as refused:
        generate(knobs, 1)
    assert refused.value.code == "playground.generation_past_its_bound"


def test_a_generation_is_bound_by_what_it_makes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(playground, "MAX_GENERATED_BYTES", 1024)
    knobs = Generation.model_validate({"fields": {"x": {"provider": "pystr", "args": {"max_chars": 5000}}}, "rows": 10})
    with pytest.raises(PlaygroundRefusal) as refused:
        generate(knobs, 1)
    assert refused.value.code == "playground.generation_past_its_bound"


def test_a_generation_stops_at_its_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(playground, "GENERATION_DEADLINE", timedelta(0))
    with pytest.raises(PlaygroundRefusal) as refused:
        generate(one("name"), 1)
    assert refused.value.code == "playground.generation_past_its_bound"


def test_a_generation_stops_when_its_caller_has(monkeypatch: pytest.MonkeyPatch) -> None:
    stopped = threading.Event()
    stopped.set()
    with pytest.raises(PlaygroundRefusal):
        generate(one("name"), 1, stopped=stopped)


async def test_a_generation_leaves_the_event_loop_turning(ctx: FakeContext) -> None:
    fields = {f"f{index}": {"provider": "json", "args": {"num_rows": 5}} for index in range(3)}
    config = {"fields": fields, "rows": 300, "seed": 1}
    pauses: list[float] = []
    started = time.monotonic()
    work = asyncio.create_task(call_block(PlaygroundOperator(), config, ctx))
    while not work.done():
        before = time.monotonic()
        await asyncio.sleep(0.005)
        pauses.append(time.monotonic() - before)
    await work
    elapsed = time.monotonic() - started
    assert elapsed > 0.2, "long enough for a pause to mean something"
    assert max(pauses) < elapsed / 2


async def test_a_refusal_off_the_loop_is_a_rejection_nothing_retries(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as refused:
        await call_block(PlaygroundOperator(), {"fields": {"x": "seed"}}, ctx)
    assert refused.value.error_class is ErrorClass.REJECTED
