"""The wire schemas themselves, rather than the calls that carry them."""

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dirigent_client.resources.base import request_body
from dirigent_client.schemas import (
    AttemptOut,
    BackfillAccepted,
    BackfilledRun,
    BackfillRequest,
    Problem,
    RunRequest,
)
from dirigent_client.schemas.common import WireModel


def test_a_shape_that_crossed_the_wire_cannot_be_edited_afterwards() -> None:
    problem = Problem(status=404, title="Not Found", detail="No pipeline goes by that name.")
    assert isinstance(problem, WireModel)
    with pytest.raises(ValidationError):
        setattr(problem, "status", 500)  # noqa: B010


def test_a_run_request_takes_both_ends_of_a_window_or_neither() -> None:
    assert RunRequest().window_start is None
    both = RunRequest(
        window_start=datetime(2026, 6, 1, tzinfo=UTC),
        window_end=datetime(2026, 6, 2, tzinfo=UTC),
    )
    assert (both.window_start, both.window_end) == (datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 2, tzinfo=UTC))

    with pytest.raises(ValidationError, match="a window has two ends"):
        RunRequest(window_start=datetime(2026, 6, 1, tzinfo=UTC))
    with pytest.raises(ValidationError, match="a window has two ends"):
        RunRequest(window_end=datetime(2026, 6, 2, tzinfo=UTC))


def test_a_run_requests_window_runs_forwards() -> None:
    with pytest.raises(ValidationError, match="runs forwards and covers something"):
        RunRequest(window_start=datetime(2026, 6, 2, tzinfo=UTC), window_end=datetime(2026, 6, 1, tzinfo=UTC))
    with pytest.raises(ValidationError, match="runs forwards and covers something"):
        RunRequest(window_start=datetime(2026, 6, 1, tzinfo=UTC), window_end=datetime(2026, 6, 1, tzinfo=UTC))


def test_a_backfill_request_spells_its_lower_bound_from_on_the_wire() -> None:
    """``from`` is a Python keyword, so the field is ``from_`` and the wire key is not."""
    request = BackfillRequest(
        schedule="nightly",
        from_=datetime(2026, 6, 1, tzinfo=UTC),
        to=datetime(2026, 6, 4, tzinfo=UTC),
    )
    assert request_body(request)["from"] == "2026-06-01T00:00:00Z"
    assert "from_" not in request_body(request)
    read = BackfillRequest.model_validate(
        {"schedule": "n", "from": "2026-06-01T00:00:00Z", "to": "2026-06-04T00:00:00Z"}
    )
    assert read.from_ == datetime(2026, 6, 1, tzinfo=UTC)


def test_a_backfill_request_runs_forwards() -> None:
    with pytest.raises(ValidationError, match="runs forwards and covers something"):
        BackfillRequest(schedule="n", from_=datetime(2026, 6, 4, tzinfo=UTC), to=datetime(2026, 6, 1, tzinfo=UTC))


def test_a_backfill_answer_counts_the_runs_it_actually_created() -> None:
    accepted = BackfillAccepted(
        pipeline="p",
        schedule="nightly",
        windows=[
            BackfilledRun(
                window_start=datetime(2026, 6, 1, tzinfo=UTC),
                window_end=datetime(2026, 6, 2, tzinfo=UTC),
                run_id=uuid.uuid4(),
            ),
            BackfilledRun(
                window_start=datetime(2026, 6, 2, tzinfo=UTC),
                window_end=datetime(2026, 6, 3, tzinfo=UTC),
                detail="a run of this pipeline is already in flight",
            ),
        ],
    )
    assert accepted.created == 1


def test_an_attempt_on_the_wire_carries_neither_of_the_engines_bookmarks() -> None:
    """A handle and a cursor are the engine's own resumption state, not a reader's."""
    assert "remote_handle" not in AttemptOut.model_fields
    assert "poke_cursor" not in AttemptOut.model_fields
