"""Tests for ``playground.arrive``: the poke sequence, and the batch the last poke carries."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from dirigent_block_base.playground import (
    ArriveOutput,
    Drift,
    PlaygroundArriveSensor,
    PlaygroundRefusal,
    parked_pokes,
)
from dirigent_plugin import ErrorClass, NotYet
from dirigent_testing import FakeContext, call_block


async def poke(ctx: FakeContext, **config: object) -> ArriveOutput | NotYet:
    """Poke the sensor once with the cursor the context holds."""
    answer = await call_block(PlaygroundArriveSensor(), config, ctx)
    assert isinstance(answer, ArriveOutput | NotYet)
    return answer


async def until_it_arrives(ctx: FakeContext, limit: int = 10, **config: object) -> tuple[list[NotYet], ArriveOutput]:
    """Poke until the batch arrives, carrying each park's cursor forward as the engine does."""
    parked: list[NotYet] = []
    for _ in range(limit):
        answer = await poke(ctx, **config)
        if isinstance(answer, ArriveOutput):
            return parked, answer
        parked.append(answer)
        ctx.cursor = dict(answer.cursor) if answer.cursor is not None else None
    raise AssertionError(f"the sensor never arrived in {limit} pokes")


def value(output: ArriveOutput, index: int = 0) -> dict[str, Any]:
    """One message's record, as the mapping every generated record is."""
    found = output.messages[index].value
    assert isinstance(found, dict)
    return found


async def test_the_first_poke_parks_and_the_second_arrives(ctx: FakeContext) -> None:
    """The default: one poke parks, so a document is seen waiting before it is seen working."""
    parked, output = await until_it_arrives(ctx, rows=3, seed=5, fields={"who": "name"})
    assert len(parked) == 1
    assert parked[0].cursor == {"pokes": 1}
    assert output.pokes == 2
    assert output.count == 3


async def test_a_park_is_not_a_failure_and_carries_what_it_is_waiting_for(ctx: FakeContext) -> None:
    answer = await poke(ctx, after_pokes=3)
    assert isinstance(answer, NotYet)
    assert answer.message == "poke 1 of 4"
    assert answer.progress == pytest.approx(0.25)


async def test_the_poke_count_comes_from_the_cursor_and_not_from_the_block(ctx: FakeContext) -> None:
    """The sensor holds nothing itself, so a poke handed a cursor carries on from it."""
    ctx.cursor = {"pokes": 4}
    output = await poke(ctx, after_pokes=4, rows=1, seed=1)
    assert isinstance(output, ArriveOutput)
    assert output.pokes == 5


async def test_a_cursor_that_says_nothing_reads_as_no_pokes() -> None:
    assert parked_pokes(None) == 0
    assert parked_pokes({}) == 0
    assert parked_pokes({"pokes": "three"}) == 0
    assert parked_pokes({"pokes": 3}) == 3


async def test_no_pokes_at_all_means_the_first_one_arrives(ctx: FakeContext) -> None:
    output = await poke(ctx, after_pokes=0, rows=2, seed=9)
    assert isinstance(output, ArriveOutput)
    assert (output.pokes, output.count) == (1, 2)


async def test_a_duration_holds_the_batch_back_however_many_pokes_have_run(ctx: FakeContext) -> None:
    """The attempt's start anchors the wait, so a fast poll does not rush it."""
    ctx.cursor = {"pokes": 9}
    answer = await poke(ctx, after_pokes=1, after="30s")
    assert isinstance(answer, NotYet)
    assert answer.next_poll_in is not None
    assert timedelta(seconds=29) < answer.next_poll_in <= timedelta(seconds=30)
    assert "of the wait left" in (answer.message or "")


async def test_a_wait_that_is_over_arrives_on_the_next_poke(ctx: FakeContext) -> None:
    ctx.started_at = datetime.now(UTC) - timedelta(seconds=30)
    output = await poke(ctx, after_pokes=0, after="1s", rows=1, seed=2)
    assert isinstance(output, ArriveOutput)
    assert output.waited_ms >= 30_000


async def test_a_poke_count_still_binds_after_the_duration_is_over(ctx: FakeContext) -> None:
    """Both knobs are floors, so the batch waits for the later of the two."""
    ctx.started_at = datetime.now(UTC) - timedelta(seconds=30)
    answer = await poke(ctx, after_pokes=2, after="1s")
    assert isinstance(answer, NotYet)
    assert answer.next_poll_in is None, "the step's own cadence decides when only pokes are left"


async def test_the_batch_is_the_same_batch_under_the_same_seed(ctx: FakeContext) -> None:
    _, first = await until_it_arrives(ctx, rows=4, seed=17, fields={"who": "name", "where": "city"})
    later = FakeContext(ctx.storage, ctx.scratch)
    _, second = await until_it_arrives(later, rows=4, seed=17, fields={"who": "name", "where": "city"})
    assert [message.value for message in first.messages] == [message.value for message in second.messages]
    assert first.seed == 17


async def test_an_unseeded_batch_says_which_seed_it_drew(ctx: FakeContext) -> None:
    _, output = await until_it_arrives(ctx, rows=2, fields={"who": "name"})
    later = FakeContext(ctx.storage, ctx.scratch)
    _, repeated = await until_it_arrives(later, rows=2, seed=output.seed, fields={"who": "name"})
    assert [message.value for message in repeated.messages] == [message.value for message in output.messages]


async def test_the_messages_are_offset_in_order(ctx: FakeContext) -> None:
    _, output = await until_it_arrives(ctx, rows=5, seed=3, fields={"who": "name"})
    assert [message.offset for message in output.messages] == [0, 1, 2, 3, 4]
    assert all(message.timestamp == output.messages[0].timestamp for message in output.messages)


async def test_drift_reaches_the_records_a_batch_carries(ctx: FakeContext) -> None:
    _, output = await until_it_arrives(ctx, rows=2, seed=3, drift="extra", fields={"who": "name"})
    assert output.drift is Drift.EXTRA
    assert value(output) == {**value(output), "drifted": True}
    assert set(value(output)) == {"who", "drifted"}


async def test_drift_that_leaves_a_field_out_leaves_it_out_of_every_message(ctx: FakeContext) -> None:
    _, output = await until_it_arrives(ctx, rows=3, seed=3, drift="missing", fields={"who": "name", "where": "city"})
    assert [set(value(output, index)) for index in range(3)] == [{"where"}] * 3


async def test_a_payload_rides_beside_the_batch_at_the_size_it_was_asked_for(ctx: FakeContext) -> None:
    _, output = await until_it_arrives(ctx, rows=1, seed=3, payload="2kb")
    assert output.payload_bytes == 2048
    assert output.payload is not None
    assert len(output.payload) == 2048


async def test_no_payload_means_no_filler(ctx: FakeContext) -> None:
    _, output = await until_it_arrives(ctx, rows=1, seed=3)
    assert (output.payload, output.payload_bytes) == (None, None)


async def test_the_batch_reports_the_knobs_that_made_it(ctx: FakeContext) -> None:
    _, output = await until_it_arrives(ctx, rows=1, seed=3, locale="no_NO", fields={"who": "name"})
    assert (output.locale, output.fields, output.drift) == ("no_NO", {"who": "name"}, Drift.NONE)


async def test_a_provider_that_is_not_one_is_refused_at_the_poke_that_would_use_it(ctx: FakeContext) -> None:
    with pytest.raises(PlaygroundRefusal) as raised:
        await poke(ctx, after_pokes=0, fields={"x": "not_a_provider"})
    assert raised.value.error_class is ErrorClass.REJECTED


async def test_a_park_never_reaches_the_field_map(ctx: FakeContext) -> None:
    """Nothing is generated until the batch arrives, so a parked poke costs one comparison."""
    answer = await poke(ctx, after_pokes=1, fields={"x": "not_a_provider"})
    assert isinstance(answer, NotYet)


async def test_more_pokes_than_the_sensor_will_park_for_are_refused(ctx: FakeContext) -> None:
    with pytest.raises(ValidationError):
        await poke(ctx, after_pokes=100_000)


async def test_a_wait_cannot_be_written_backwards(ctx: FakeContext) -> None:
    with pytest.raises(ValidationError):
        await poke(ctx, after="-5s")
