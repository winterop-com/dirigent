"""A pipeline's triggers over the API: the clocks it keeps, and the token it shows once."""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

from tests_support import DOCUMENT, apply_document

PREFIX = "/api/v1"
SCHEDULES = f"{PREFIX}/pipelines/api-demo/triggers/schedules"
PREVIEW = f"{PREFIX}/schedules/$preview"
WEBHOOKS = f"{PREFIX}/pipelines/api-demo/triggers/webhooks"

#: Both must stay far enough ahead that the embedded scheduler cannot fire them mid-test.
NIGHTLY = "0 3 * * *"
DISTANT = "2999-01-01T00:00:00Z"

#: The same pipeline, declaring the clock in the document rather than over the API.
WITH_SCHEDULE = (
    DOCUMENT
    + f"""
triggers:
  schedules:
    - code: nightly
      cron: "{NIGHTLY}"
"""
)


def instant(value: str) -> datetime:
    """Read an instant out of a response."""
    return datetime.fromisoformat(value)


def create_schedule(client: TestClient, **payload: Any) -> dict[str, Any]:
    """Declare one schedule and return the row the API answered with."""
    response = client.post(SCHEDULES, json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def create_webhook(client: TestClient, **payload: Any) -> dict[str, Any]:
    """Declare one webhook and return the minted token."""
    response = client.post(WEBHOOKS, json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_cron_schedule_carries_its_zone_its_parameters_and_a_computed_next_firing(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    created = create_schedule(
        client,
        code="nightly",
        cron=NIGHTLY,
        timezone="Europe/Oslo",
        params={"greeting": "good morning"},
    )
    assert created["kind"] == "cron"
    assert created["cron"] == NIGHTLY
    assert created["timezone"] == "Europe/Oslo"
    assert created["params"] == {"greeting": "good morning"}
    assert created["interval"] is None
    assert created["paused"] is False
    assert instant(created["next_fire_at"]) > datetime.now(UTC), "the first firing is computed at declaration time"
    assert created["last_fired_at"] is None


def test_an_interval_schedule_reads_back_as_the_humane_duration_it_was_written_as(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    created = create_schedule(client, code="hourly", interval="90m")
    assert created["kind"] == "interval"
    assert created["interval"] == "1h30m", "an interval is a duration, not a number of seconds"
    assert isinstance(created["interval"], str)
    assert created["cron"] is None
    assert instant(created["next_fire_at"]) > datetime.now(UTC)


def test_a_one_time_schedule_fires_at_the_instant_it_names(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    created = create_schedule(client, code="once", at=DISTANT)
    assert created["kind"] == "one_time"
    assert instant(created["at"]) == instant(DISTANT)
    assert instant(created["next_fire_at"]) == instant(DISTANT)


def test_a_schedule_declares_exactly_one_clock(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    two = client.post(SCHEDULES, json={"code": "both", "cron": NIGHTLY, "interval": "1h"})
    assert two.status_code == 422
    assert "exactly one of cron, interval, or at" in two.json()["detail"]
    none = client.post(SCHEDULES, json={"code": "neither"})
    assert none.status_code == 422
    assert "(none)" in none.json()["detail"]


def test_a_schedule_declares_the_levels_its_runs_keep(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    created = client.post(SCHEDULES, json={"code": "loud", "cron": NIGHTLY, "log_levels": {"*": "debug"}})

    assert created.status_code == 201, created.text
    assert created.json()["log_levels"] == {"*": "debug"}
    empty = client.post(SCHEDULES, json={"code": "hollow", "cron": NIGHTLY, "log_levels": {"": "debug"}})
    assert empty.status_code == 422
    assert "a pattern may not be empty" in empty.text


def test_a_schedule_declares_the_priority_its_runs_carry(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    created = client.post(SCHEDULES, json={"code": "urgent", "cron": NIGHTLY, "priority": "high"})

    assert created.status_code == 201, created.text
    assert created.json()["priority"] == "high"
    inherited = client.post(SCHEDULES, json={"code": "ordinary", "cron": NIGHTLY})
    assert inherited.json()["priority"] is None, "an undeclared priority takes the pipeline's own"


def test_a_cron_clock_is_read_back_as_the_firings_it_would_make(client: TestClient) -> None:
    read = client.post(PREVIEW, json={"cron": NIGHTLY, "timezone": "Europe/Oslo"})

    assert read.status_code == 200, read.text
    firings = [instant(one) for one in read.json()["firings"]]
    assert len(firings) == 3
    assert firings[0] > datetime.now(UTC)
    assert firings == sorted(firings)
    assert firings[1] - firings[0] == timedelta(days=1)


def test_an_interval_clock_is_read_back_at_its_own_cadence(client: TestClient) -> None:
    read = client.post(PREVIEW, json={"interval": "15m"})

    assert read.status_code == 200, read.text
    firings = [instant(one) for one in read.json()["firings"]]
    assert len(firings) == 3
    assert firings[2] - firings[0] == timedelta(minutes=30)


def test_a_one_time_clock_is_read_back_as_the_one_moment_it_names(client: TestClient) -> None:
    read = client.post(PREVIEW, json={"at": DISTANT})

    assert read.status_code == 200, read.text
    assert [instant(one) for one in read.json()["firings"]] == [instant(DISTANT)]

    gone = client.post(PREVIEW, json={"at": "2000-01-01T00:00:00Z"})
    assert gone.status_code == 200, gone.text
    assert gone.json()["firings"] == [], "a moment that has passed fires at no instant"


def test_a_clock_nothing_can_read_is_answered_with_the_parser_own_sentence(client: TestClient) -> None:
    bad_cron = client.post(PREVIEW, json={"cron": "not a cron expression"})
    assert bad_cron.status_code == 422
    assert "is not a cron expression" in bad_cron.json()["detail"]

    bad_interval = client.post(PREVIEW, json={"interval": "15x"})
    assert bad_interval.status_code == 422
    assert "is not a duration" in bad_interval.json()["detail"]

    bad_moment = client.post(PREVIEW, json={"at": "soon"})
    assert bad_moment.status_code == 422
    assert "is not a moment" in bad_moment.json()["detail"]

    bad_zone = client.post(PREVIEW, json={"cron": NIGHTLY, "timezone": "Mars/Olympus"})
    assert bad_zone.status_code == 422
    assert "is not an IANA timezone" in bad_zone.json()["detail"]

    nothing = client.post(PREVIEW, json={})
    assert nothing.status_code == 422
    assert "(none)" in nothing.json()["detail"]


def test_a_clock_nothing_can_read_is_refused_at_declaration_time(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    bad_cron = client.post(SCHEDULES, json={"code": "broken", "cron": "not a cron expression"})
    assert bad_cron.status_code == 422
    assert "is not a cron expression" in bad_cron.json()["detail"]
    bad_zone = client.post(SCHEDULES, json={"code": "elsewhere", "cron": NIGHTLY, "timezone": "Mars/Olympus"})
    assert bad_zone.status_code == 422
    assert "is not an IANA timezone" in bad_zone.json()["detail"]


def test_a_pinned_parameter_the_schema_refuses_is_refused_at_declaration_time(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    refused = client.post(SCHEDULES, json={"code": "nightly", "cron": NIGHTLY, "params": {"greeting": 5}})
    assert refused.status_code == 422
    assert "parameter greeting is invalid" in refused.json()["detail"]
    assert client.get(SCHEDULES).json()["items"] == [], "a schedule nothing can fire is never stored"

    created = create_schedule(client, code="nightly", cron=NIGHTLY, params={"greeting": "good morning"})
    assert created["params"] == {"greeting": "good morning"}

    redeclared = client.patch(
        f"{SCHEDULES}/nightly", json={"code": "nightly", "interval": "1h", "params": {"greeting": 5}}
    )
    assert redeclared.status_code == 422
    assert "parameter greeting is invalid" in redeclared.json()["detail"]
    assert client.get(f"{SCHEDULES}/nightly").json()["params"] == {"greeting": "good morning"}


def test_two_schedules_on_one_pipeline_may_not_share_a_code(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron=NIGHTLY)
    again = client.post(SCHEDULES, json={"code": "nightly", "cron": NIGHTLY})
    assert again.status_code == 409
    assert "already has a schedule coded 'nightly'" in again.json()["detail"]


def test_a_schedule_on_a_pipeline_that_does_not_exist_is_a_404(client: TestClient) -> None:
    response = client.post(
        f"{PREFIX}/pipelines/nobody-home/triggers/schedules",
        json={"code": "nightly", "cron": NIGHTLY},
    )
    assert response.status_code == 404
    assert client.get(f"{PREFIX}/pipelines/nobody-home/triggers/schedules").status_code == 404


def test_schedules_are_listed_and_can_be_redeclared(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron=NIGHTLY, params={"greeting": "good morning"})
    create_schedule(client, code="hourly", interval="1h")
    listed = client.get(SCHEDULES).json()["items"]
    assert [row["code"] for row in listed] == ["hourly", "nightly"]

    updated = client.patch(f"{SCHEDULES}/nightly", json={"code": "nightly", "interval": "2h"})
    assert updated.status_code == 200
    assert updated.json()["kind"] == "interval"
    assert updated.json()["interval"] == "2h"
    assert updated.json()["cron"] is None
    assert updated.json()["params"] == {}, "a redeclaration is the whole schedule, not a patch of it"
    assert client.patch(f"{SCHEDULES}/nobody", json={"code": "nobody", "interval": "2h"}).status_code == 404


def test_a_redeclaration_that_names_no_clock_is_refused(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron=NIGHTLY)
    refused = client.patch(f"{SCHEDULES}/nightly", json={"code": "nightly"})
    assert refused.status_code == 422
    assert "exactly one of cron, interval, or at" in refused.json()["detail"]


def test_pausing_stops_a_schedule_and_resuming_starts_its_clock_afresh(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    created = create_schedule(client, code="hourly", interval="1h")

    paused = client.post(f"{SCHEDULES}/hourly/$pause")
    assert paused.status_code == 200
    assert paused.json()["paused"] is True

    resumed = client.post(f"{SCHEDULES}/hourly/$resume")
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False
    assert instant(resumed.json()["next_fire_at"]) > instant(created["next_fire_at"]), (
        "resuming recomputes the next firing from now rather than replaying the missed slots"
    )


def test_a_redeclaration_keeps_a_schedule_paused(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron=NIGHTLY)
    assert client.post(f"{SCHEDULES}/nightly/$pause").json()["paused"] is True
    updated = client.patch(f"{SCHEDULES}/nightly", json={"code": "nightly", "cron": "0 4 * * *"})
    assert updated.json()["paused"] is True, "pausing is an operator's decision, not part of the declaration"


def test_an_apply_that_asks_for_paused_schedules_materialises_them_paused(client: TestClient) -> None:
    result = apply_document(client, WITH_SCHEDULE, pause_schedules=True)
    assert result["triggers"]["schedules_created"] == ["nightly"]

    rows = client.get(SCHEDULES).json()["items"]
    assert [row["code"] for row in rows] == ["nightly"]
    assert rows[0]["paused"] is True
    assert rows[0]["next_fire_at"] is not None


def test_a_plain_apply_materialises_a_schedule_that_is_running(client: TestClient) -> None:
    apply_document(client, WITH_SCHEDULE)
    assert client.get(SCHEDULES).json()["items"][0]["paused"] is False


def test_reapplying_without_the_flag_leaves_a_schedule_an_operator_resumed_alone(client: TestClient) -> None:
    apply_document(client, WITH_SCHEDULE, pause_schedules=True)
    assert client.post(f"{SCHEDULES}/nightly/$resume").json()["paused"] is False

    changed = WITH_SCHEDULE.replace(NIGHTLY, "0 4 * * *")
    assert apply_document(client, changed)["triggers"]["schedules_updated"] == ["nightly"]

    row = client.get(SCHEDULES).json()["items"][0]
    assert row["cron"] == "0 4 * * *"
    assert row["paused"] is False, "--paused governs what an apply creates, not what already runs"


def test_a_schedule_that_has_never_fired_has_an_empty_history(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron=NIGHTLY)
    firings = client.get(f"{SCHEDULES}/nightly/firings")
    assert firings.status_code == 200
    assert firings.json()["items"] == []
    assert client.get(f"{SCHEDULES}/nightly/firings", params={"limit": 0}).status_code == 422


def test_a_deleted_schedule_is_gone(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron=NIGHTLY)
    assert client.delete(f"{SCHEDULES}/nightly").status_code == 204
    assert client.get(f"{SCHEDULES}/nightly/firings").status_code == 404
    assert client.delete(f"{SCHEDULES}/nightly").status_code == 404
    assert client.get(SCHEDULES).json()["items"] == []


def test_a_minted_webhook_shows_its_token_once_and_the_path_to_present_it_at(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    minted = create_webhook(client, code="from-github", params_from_payload={"greeting": "$.message.text"})
    token = minted["token"]
    assert token
    assert minted["prefix"] == token[:8]
    assert minted["url_path"] == f"/hooks/{token}"
    assert minted["code"] == "from-github"


def test_a_listing_shows_a_prefix_and_never_the_token(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    minted = create_webhook(client, code="from-github", hmac_secret="a shared secret", rate_limit_per_minute=10)
    listing = client.get(WEBHOOKS)
    assert listing.status_code == 200
    assert minted["token"] not in listing.text, "the instance keeps only the hash and must never echo the token"
    assert "a shared secret" not in listing.text
    row = listing.json()["items"][0]
    assert row["token_prefix"] == minted["prefix"]
    assert "token" not in row
    assert row["signed"] is True
    assert row["active"] is True
    assert row["rate_limit_per_minute"] == 10
    assert row["last_delivery_at"] is None


def test_two_webhooks_on_one_pipeline_may_not_share_a_code(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_webhook(client, code="from-github")
    again = client.post(WEBHOOKS, json={"code": "from-github"})
    assert again.status_code == 409
    assert "already has a webhook coded 'from-github'" in again.json()["detail"]


def test_a_mapping_no_delivery_could_satisfy_is_refused_when_the_webhook_is_declared(
    client: TestClient,
) -> None:
    """Every problem at once, so a caller fixes the mapping in one round trip."""
    apply_document(client, DOCUMENT)
    refused = client.post(
        WEBHOOKS,
        json={"code": "from-github", "params_from_payload": {"greeting": "$.message..text", "nonsense": "$.a"}},
    )
    assert refused.status_code == 422
    detail = refused.json()["detail"]
    assert "'$.message..text' is not a payload path: an empty segment" in detail
    assert "'nonsense' is not a parameter this pipeline declares (greeting)" in detail
    assert client.get(WEBHOOKS).json()["items"] == []


def test_a_mapping_the_pipeline_declares_is_accepted(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_webhook(client, code="from-github", params_from_payload={"greeting": "$.message.0.text"})
    assert client.get(WEBHOOKS).json()["items"][0]["params_from_payload"] == {"greeting": "$.message.0.text"}


def test_a_webhook_on_a_pipeline_that_does_not_exist_is_a_404(client: TestClient) -> None:
    response = client.post(f"{PREFIX}/pipelines/nobody-home/triggers/webhooks", json={"code": "x"})
    assert response.status_code == 404


def test_rotating_a_token_mints_a_different_one(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    minted = create_webhook(client, code="from-github")
    rotated = client.post(f"{WEBHOOKS}/from-github/$rotate-token")
    assert rotated.status_code == 200
    assert rotated.json()["token"] != minted["token"]
    assert rotated.json()["url_path"] == f"/hooks/{rotated.json()['token']}"
    assert client.get(WEBHOOKS).json()["items"][0]["token_prefix"] == rotated.json()["prefix"]
    assert client.post(f"{WEBHOOKS}/nobody/$rotate-token").status_code == 404


def test_a_webhook_can_be_disabled_and_enabled_without_losing_its_token(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    minted = create_webhook(client, code="from-github")
    disabled = client.post(f"{WEBHOOKS}/from-github/$disable")
    assert disabled.status_code == 200
    assert disabled.json()["active"] is False
    assert disabled.json()["token_prefix"] == minted["prefix"]
    assert client.post(f"{WEBHOOKS}/from-github/$enable").json()["active"] is True


def test_a_webhook_that_has_received_nothing_has_an_empty_delivery_history(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_webhook(client, code="from-github")
    deliveries = client.get(f"{WEBHOOKS}/from-github/deliveries")
    assert deliveries.status_code == 200
    assert deliveries.json()["items"] == []
    assert client.get(f"{WEBHOOKS}/nobody/deliveries").status_code == 404


def test_a_deleted_webhook_is_gone(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_webhook(client, code="from-github")
    assert client.delete(f"{WEBHOOKS}/from-github").status_code == 204
    assert client.get(WEBHOOKS).json()["items"] == []
    assert client.delete(f"{WEBHOOKS}/from-github").status_code == 404


def test_every_trigger_route_refuses_an_anonymous_request(anonymous: TestClient) -> None:
    for method, path in [
        ("get", "/triggers/schedules"),
        ("post", "/triggers/schedules"),
        ("patch", "/triggers/schedules/nightly"),
        ("post", "/triggers/schedules/nightly/$pause"),
        ("post", "/triggers/schedules/nightly/$resume"),
        ("get", "/triggers/schedules/nightly/firings"),
        ("delete", "/triggers/schedules/nightly"),
        ("get", "/triggers/webhooks"),
        ("post", "/triggers/webhooks"),
        ("post", "/triggers/webhooks/from-github/$rotate-token"),
        ("post", "/triggers/webhooks/from-github/$disable"),
        ("post", "/triggers/webhooks/from-github/$enable"),
        ("get", "/triggers/webhooks/from-github/deliveries"),
        ("delete", "/triggers/webhooks/from-github"),
    ]:
        response = anonymous.request(method, f"{PREFIX}/pipelines/api-demo{path}", json={})
        assert response.status_code == 401, f"{method} {path} let an anonymous request through"
        assert "authentication required" in response.json()["detail"]


# -- backfill: the windows a cadence has already gone past ------------------------

BACKFILL = f"{PREFIX}/pipelines/api-demo/$backfill"


def backfill(client: TestClient, **payload: Any) -> dict[str, Any]:
    """Ask for one backfill and return the plan the API answered with."""
    response = client.post(BACKFILL, json=payload)
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_backfill_enumerates_the_lower_bound_and_not_the_upper_and_fills_in_order(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron="0 5 * * *", timezone="UTC")

    accepted = backfill(
        client,
        schedule="nightly",
        **{"from": "2026-06-01T05:00:00Z"},
        to="2026-06-04T05:00:00Z",
    )

    assert accepted["pipeline"] == "api-demo"
    assert accepted["schedule"] == "nightly"
    assert accepted["dry_run"] is False
    ends = [instant(one["window_end"]) for one in accepted["windows"]]
    assert ends == [
        datetime(2026, 6, 1, 5, 0, tzinfo=UTC),
        datetime(2026, 6, 2, 5, 0, tzinfo=UTC),
        datetime(2026, 6, 3, 5, 0, tzinfo=UTC),
    ], "the lower bound is enumerated and the upper one is not, oldest first"
    starts = [instant(one["window_start"]) for one in accepted["windows"]]
    assert starts == [end - timedelta(days=1) for end in ends]
    assert all(one["run_id"] for one in accepted["windows"])


def test_every_backfilled_run_carries_its_own_window_and_says_a_backfill_made_it(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron="0 5 * * *", timezone="UTC")

    accepted = backfill(client, schedule="nightly", **{"from": "2026-06-01T05:00:00Z"}, to="2026-06-03T05:00:00Z")

    for one in accepted["windows"]:
        run = client.get(f"{PREFIX}/runs/{one['run_id']}").json()["run"]
        assert run["triggered_by_kind"] == "backfill"
        assert run["triggered_by_label"] == "backfill nightly"
        assert instant(run["window_start"]) == instant(one["window_start"])
        assert instant(run["window_end"]) == instant(one["window_end"])


def test_a_dry_run_answers_with_the_same_plan_and_creates_nothing(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron="0 5 * * *", timezone="UTC")
    before = len(client.get(f"{PREFIX}/runs").json()["items"])

    planned = backfill(
        client,
        schedule="nightly",
        **{"from": "2026-06-01T05:00:00Z"},
        to="2026-06-04T05:00:00Z",
        dry_run=True,
    )

    assert planned["dry_run"] is True
    assert len(planned["windows"]) == 3
    assert [one["run_id"] for one in planned["windows"]] == [None, None, None]
    assert len(client.get(f"{PREFIX}/runs").json()["items"]) == before


def test_a_backfill_past_the_cap_is_refused_naming_the_cap_and_the_count(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron="0 5 * * *", timezone="UTC")

    refused = client.post(
        BACKFILL,
        json={"schedule": "nightly", "from": "2026-01-01T00:00:00Z", "to": "2027-01-01T00:00:00Z"},
    )

    assert refused.status_code == 422, refused.text
    detail = refused.json()["detail"]
    assert "at most 200 runs" in detail
    assert "enumerates 365" in detail
    assert client.get(f"{PREFIX}/runs").json()["items"] == []


def test_a_backfill_far_past_the_counting_ceiling_says_more_than_it_counted(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="every-minute", interval="1m")

    refused = client.post(
        BACKFILL,
        json={"schedule": "every-minute", "from": "2026-01-01T00:00:00Z", "to": "2026-02-01T00:00:00Z"},
    )

    assert refused.status_code == 422, refused.text
    assert "more than 2000" in refused.json()["detail"]


def test_a_one_time_schedule_has_no_cadence_to_backfill(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="launch", at=DISTANT)

    refused = client.post(
        BACKFILL,
        json={"schedule": "launch", "from": "2026-01-01T00:00:00Z", "to": "2026-01-05T00:00:00Z"},
    )

    assert refused.status_code == 422, refused.text
    assert "no cadence to enumerate" in refused.json()["detail"]


def test_a_backfill_of_a_schedule_this_pipeline_does_not_have_is_a_404(client: TestClient) -> None:
    apply_document(client, DOCUMENT)

    refused = client.post(
        BACKFILL,
        json={"schedule": "nobody-home", "from": "2026-01-01T00:00:00Z", "to": "2026-01-05T00:00:00Z"},
    )

    assert refused.status_code == 404, refused.text
    assert "no schedule coded 'nobody-home'" in refused.json()["detail"]


def test_a_backwards_backfill_interval_is_refused_by_the_body_itself(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron="0 5 * * *", timezone="UTC")

    refused = client.post(
        BACKFILL,
        json={"schedule": "nightly", "from": "2026-06-04T00:00:00Z", "to": "2026-06-01T00:00:00Z"},
    )

    assert refused.status_code == 422, refused.text
    assert "runs forwards and covers something" in refused.text


def test_a_backfill_takes_the_schedules_pinned_parameters_unless_it_is_given_others(client: TestClient) -> None:
    apply_document(client, DOCUMENT)
    create_schedule(client, code="nightly", cron="0 5 * * *", timezone="UTC", params={"greeting": "pinned"})

    pinned = backfill(client, schedule="nightly", **{"from": "2026-06-01T05:00:00Z"}, to="2026-06-02T05:00:00Z")
    given = backfill(
        client,
        schedule="nightly",
        **{"from": "2026-06-02T05:00:00Z"},
        to="2026-06-03T05:00:00Z",
        params={"greeting": "given"},
    )

    assert _params_of(client, pinned) == {"greeting": "pinned"}
    assert _params_of(client, given) == {"greeting": "given"}


def _params_of(client: TestClient, accepted: dict[str, Any]) -> dict[str, Any]:
    """Read the parameters of the one run a backfill created."""
    run_id = accepted["windows"][0]["run_id"]
    params: dict[str, Any] = client.get(f"{PREFIX}/runs/{run_id}").json()["run"]["params"]
    return params


#: The same pipeline, refusing a second run while one is in flight.
SKIPPING = DOCUMENT.replace("code: api-demo", "code: api-demo\nconcurrency: skip")


def test_a_backfill_leaves_the_concurrency_policy_in_charge_and_says_what_it_refused(
    client: TestClient,
) -> None:
    """A `skip` pipeline fills its first window and declines the rest, per window."""
    apply_document(client, SKIPPING)
    create_schedule(client, code="nightly", cron="0 5 * * *", timezone="UTC")

    accepted = backfill(client, schedule="nightly", **{"from": "2026-06-01T05:00:00Z"}, to="2026-06-04T05:00:00Z")

    windows = accepted["windows"]
    assert len(windows) == 3, "every window is still enumerated and reported on"
    assert windows[0]["run_id"] is not None
    assert [one["run_id"] for one in windows[1:]] == [None, None]
    assert all(one["detail"] == "a run of this pipeline is already in flight" for one in windows[1:])
