"""A ``kind: triggers`` document: what it declares, what it owns, and what it refuses."""

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import DocumentKind, ProvenanceSource
from dirigent_client.schemas import ApplyResult, PlanAction
from dirigent_core.database import session_scope
from dirigent_core.documents import DocumentError, load_text
from dirigent_core.engine import Provenance
from dirigent_core.engine.definition import TriggersDefinition
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import Schedule, TriggerDocument, WebhookTrigger
from dirigent_core.pipelines import apply_document, delete_pipeline, find_pipeline, set_active
from dirigent_core.trigger_documents import (
    delete_absent_trigger_documents,
    delete_trigger_document,
    find_trigger_document,
    list_trigger_documents,
    owned_codes,
)
from dirigent_core.triggers import create_schedule
from dirigent_core.triggers.schedules import ScheduleRequest

PIPELINE = """
format: dirigent/v1
kind: pipeline
code: batch-fleet
description: A pipeline somebody else's document schedules.
params:
  type: object
  properties:
    day: { type: string, default: "2026-01-01" }
  additionalProperties: false
steps:
  load:
    block: test.echo
    config: { value: one }
triggers:
  schedules:
    - code: inline-nightly
      cron: "0 5 * * *"
"""

TRIGGERS = """
format: dirigent/v1
kind: triggers
code: fleet-clocks
name: Fleet clocks
description: The operations team's clocks over a pipeline another document defines.
pipeline: batch-fleet
triggers:
  schedules:
    - code: ops-nightly
      cron: "0 4 * * *"
      params: { day: "2026-02-02" }
  webhooks:
    - code: ops-kick
      params_from_payload: { day: "$.run.date" }
"""


async def apply(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    text: str,
    *,
    dry_run: bool = False,
    pause_schedules: bool = False,
    provenance: Provenance | None = None,
) -> ApplyResult:
    """Apply one document of either kind, each in its own transaction."""
    async with session_scope(sessions) as session:
        return await apply_document(
            session,
            services,
            load_text(text),
            dry_run=dry_run,
            pause_schedules=pause_schedules,
            provenance=provenance,
        )


async def codes(sessions: async_sessionmaker[AsyncSession]) -> dict[str, str | None]:
    """Every schedule on the instance, and the code of whichever document owns it."""
    async with session_scope(sessions) as session:
        rows = list((await session.execute(sa.select(Schedule))).scalars())
        documents = {row.id: row.code for row in (await session.execute(sa.select(TriggerDocument))).scalars()}
        return {row.code: documents.get(row.trigger_document_id) if row.trigger_document_id else None for row in rows}


# The model itself.


def test_a_triggers_document_declares_a_pipeline_and_its_clocks() -> None:
    definition = load_text(TRIGGERS)
    assert isinstance(definition, TriggersDefinition)
    assert definition.kind == "triggers"
    assert definition.pipeline == "batch-fleet"
    assert [spec.code for spec in definition.triggers.schedules] == ["ops-nightly"]
    assert [spec.code for spec in definition.triggers.webhooks] == ["ops-kick"]


def test_an_empty_triggers_section_is_a_document_that_retires_everything() -> None:
    definition = load_text("format: dirigent/v1\nkind: triggers\ncode: quiet\npipeline: batch-fleet\n")
    assert isinstance(definition, TriggersDefinition)
    assert definition.triggers.empty


def test_a_triggers_document_refuses_a_schedule_with_no_clock() -> None:
    with pytest.raises(DocumentError) as raised:
        load_text(
            "format: dirigent/v1\nkind: triggers\ncode: clocks\npipeline: batch-fleet\n"
            "triggers:\n  schedules:\n    - code: whenever\n"
        )
    assert "exactly one of cron, interval, or at" in str(raised.value)


def test_a_triggers_document_refuses_two_schedules_of_one_code() -> None:
    with pytest.raises(DocumentError) as raised:
        load_text(
            "format: dirigent/v1\nkind: triggers\ncode: clocks\npipeline: batch-fleet\n"
            "triggers:\n  schedules:\n"
            "    - { code: twice, cron: '0 5 * * *' }\n"
            "    - { code: twice, interval: 1h }\n"
        )
    assert "duplicate schedule codes: twice" in str(raised.value)


def test_a_triggers_document_refuses_a_key_the_format_does_not_define() -> None:
    with pytest.raises(DocumentError) as raised:
        load_text("format: dirigent/v1\nkind: triggers\ncode: clocks\npipeline: p\nsteps: {}\n")
    assert "steps: unknown key" in str(raised.value)


def test_the_envelope_accepts_both_kinds_and_names_the_two_it_knows() -> None:
    assert load_text(TRIGGERS).kind == "triggers"
    with pytest.raises(DocumentError) as raised:
        load_text("format: dirigent/v1\nkind: widget\ncode: nope\n")
    assert "`kind: pipeline` and `kind: triggers`" in str(raised.value)
    assert "'widget'" in str(raised.value)


# Applying it.


async def test_applying_one_creates_the_document_and_its_rows(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)

    result = await apply(sessions, services, TRIGGERS)

    assert result.kind is DocumentKind.TRIGGERS
    assert result.plan.action is PlanAction.CREATE
    assert result.plan.pipeline == "batch-fleet"
    assert result.version is None
    assert result.triggers.schedules_created == ["ops-nightly"]
    assert result.triggers.webhooks_created == ["ops-kick"]
    assert await codes(sessions) == {"inline-nightly": None, "ops-nightly": "fleet-clocks"}


async def test_re_applying_an_unchanged_document_reports_unchanged(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS)

    again = await apply(sessions, services, TRIGGERS)

    assert again.plan.action is PlanAction.UNCHANGED


async def test_an_unchanged_re_apply_still_reconciles(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The digest covers the document, not the instance, so a deleted clock comes back."""
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS)
    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Schedule).where(Schedule.code == "ops-nightly"))).scalar_one()
        await session.delete(row)

    again = await apply(sessions, services, TRIGGERS)

    assert again.plan.action is PlanAction.UNCHANGED
    assert again.triggers.schedules_created == ["ops-nightly"]


async def test_a_changed_document_updates_and_retires_what_it_stopped_declaring(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS)

    changed = await apply(
        sessions,
        services,
        "format: dirigent/v1\nkind: triggers\ncode: fleet-clocks\nname: Fleet clocks\n"
        "description: The operations team's clocks over a pipeline another document defines.\n"
        "pipeline: batch-fleet\n"
        "triggers:\n  schedules:\n    - { code: ops-nightly, cron: '0 6 * * *' }\n",
    )

    assert changed.plan.action is PlanAction.UPDATE
    assert changed.triggers.schedules_updated == ["ops-nightly"]
    assert changed.triggers.webhooks_removed == ["ops-kick"]
    assert await codes(sessions) == {"inline-nightly": None, "ops-nightly": "fleet-clocks"}


async def test_a_dry_run_writes_nothing(sessions: async_sessionmaker[AsyncSession], services: EngineServices) -> None:
    await apply(sessions, services, PIPELINE)

    planned = await apply(sessions, services, TRIGGERS, dry_run=True)

    assert planned.plan.action is PlanAction.CREATE
    assert planned.dry_run
    async with session_scope(sessions) as session:
        assert await find_trigger_document(session, "fleet-clocks") is None


async def test_pause_schedules_reaches_the_schedules_a_triggers_document_mints(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)

    await apply(sessions, services, TRIGGERS, pause_schedules=True)

    async with session_scope(sessions) as session:
        row = (await session.execute(sa.select(Schedule).where(Schedule.code == "ops-nightly"))).scalar_one()
        assert row.paused


# What it refuses.


async def test_a_document_naming_a_pipeline_no_instance_holds_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    result = await apply(sessions, services, TRIGGERS)

    assert result.plan.action is PlanAction.INVALID
    assert [issue.location for issue in result.plan.issues] == ["pipeline"]
    assert "apply it before the document that schedules it" in result.plan.issues[0].message
    assert await codes(sessions) == {}


async def test_a_document_naming_an_inactive_pipeline_is_refused(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    async with session_scope(sessions) as session:
        await set_active(session, "batch-fleet", active=False)

    result = await apply(sessions, services, TRIGGERS)

    assert result.plan.action is PlanAction.INVALID
    assert [issue.location for issue in result.plan.issues] == ["pipeline"]
    assert "is inactive" in result.plan.issues[0].message


async def test_pinned_parameters_are_checked_against_the_pipelines_current_version(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)

    result = await apply(
        sessions,
        services,
        "format: dirigent/v1\nkind: triggers\ncode: fleet-clocks\npipeline: batch-fleet\n"
        "triggers:\n  schedules:\n    - { code: ops, cron: '0 4 * * *', params: { nonsense: 1 } }\n",
    )

    assert result.plan.action is PlanAction.INVALID
    assert [issue.location for issue in result.plan.issues] == ["triggers.schedules[0].params"]


async def test_a_webhook_mapping_is_checked_against_the_pipelines_current_version(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)

    result = await apply(
        sessions,
        services,
        "format: dirigent/v1\nkind: triggers\ncode: fleet-clocks\npipeline: batch-fleet\n"
        "triggers:\n  webhooks:\n    - { code: ops-kick, params_from_payload: { nonsense: '$.a' } }\n",
    )

    assert result.plan.action is PlanAction.INVALID
    assert [issue.location for issue in result.plan.issues] == ["triggers.webhooks[0].params_from_payload"]
    assert result.plan.issues[0].message == "'nonsense' is not a parameter this pipeline declares (day)"


# Ownership.


async def test_a_code_the_pipelines_own_document_declares_is_refused_by_name(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)

    result = await apply(
        sessions,
        services,
        "format: dirigent/v1\nkind: triggers\ncode: fleet-clocks\npipeline: batch-fleet\n"
        "triggers:\n  schedules:\n    - { code: inline-nightly, cron: '0 4 * * *' }\n",
    )

    assert result.plan.action is PlanAction.INVALID
    assert [issue.location for issue in result.plan.issues] == ["triggers.schedules[0].code"]
    assert result.plan.issues[0].message == (
        "schedule 'inline-nightly' on pipeline 'batch-fleet' is declared by the pipeline's own document"
    )


async def test_a_hand_made_code_is_refused_and_named_as_such(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "batch-fleet")
        assert pipeline is not None
        await create_schedule(session, pipeline, ScheduleRequest(code="by-hand", cron="0 7 * * 1"))

    result = await apply(
        sessions,
        services,
        "format: dirigent/v1\nkind: triggers\ncode: fleet-clocks\npipeline: batch-fleet\n"
        "triggers:\n  schedules:\n    - { code: by-hand, cron: '0 4 * * *' }\n",
    )

    assert result.plan.issues[0].message.endswith("is declared by hand, through the API")


async def test_the_inline_reconcile_never_touches_a_triggers_documents_rows(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS)

    again = await apply(sessions, services, PIPELINE)

    assert again.triggers.schedules_removed == []
    assert await codes(sessions) == {"inline-nightly": None, "ops-nightly": "fleet-clocks"}


async def test_a_triggers_documents_reconcile_never_touches_the_inline_rows(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS)

    emptied = await apply(
        sessions,
        services,
        "format: dirigent/v1\nkind: triggers\ncode: fleet-clocks\npipeline: batch-fleet\n",
    )

    assert emptied.triggers.schedules_removed == ["ops-nightly"]
    assert await codes(sessions) == {"inline-nightly": None}


async def test_a_hand_made_schedule_survives_both_reconciles(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "batch-fleet")
        assert pipeline is not None
        await create_schedule(session, pipeline, ScheduleRequest(code="by-hand", cron="0 7 * * 1"))
    await apply(sessions, services, TRIGGERS)

    await apply(sessions, services, PIPELINE)

    assert await codes(sessions) == {
        "by-hand": None,
        "inline-nightly": None,
        "ops-nightly": "fleet-clocks",
    }


async def test_a_code_another_triggers_document_declares_is_refused_by_that_documents_code(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS)

    result = await apply(
        sessions,
        services,
        "format: dirigent/v1\nkind: triggers\ncode: other-clocks\npipeline: batch-fleet\n"
        "triggers:\n  schedules:\n    - { code: ops-nightly, cron: '0 9 * * *' }\n",
    )

    assert result.plan.issues[0].message.endswith("is declared by the triggers document 'fleet-clocks'")


# Reading, removing, and pruning.


async def test_reading_one_lists_the_rows_it_owns(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS)

    async with session_scope(sessions) as session:
        rows = await list_trigger_documents(session)
        assert [row.code for row in rows] == ["fleet-clocks"]
        assert await owned_codes(session, rows[0].id) == (["ops-nightly"], ["ops-kick"])


async def test_deleting_one_takes_its_rows_and_leaves_the_pipelines_own(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS)

    async with session_scope(sessions) as session:
        row = await find_trigger_document(session, "fleet-clocks")
        assert row is not None
        await delete_trigger_document(session, row)

    assert await codes(sessions) == {"inline-nightly": None}
    async with session_scope(sessions) as session:
        assert (await session.execute(sa.select(WebhookTrigger))).scalars().all() == []


async def test_deleting_the_pipeline_takes_its_triggers_documents_with_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS)

    async with session_scope(sessions) as session:
        await delete_pipeline(session, "batch-fleet")

    async with session_scope(sessions) as session:
        assert await list_trigger_documents(session) == []


async def test_a_prune_deletes_only_the_directory_provenance_documents_a_directory_dropped(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS, provenance=Provenance(source=ProvenanceSource.DIRECTORY, ref="a.yaml"))
    await apply(
        sessions,
        services,
        "format: dirigent/v1\nkind: triggers\ncode: hand-clocks\npipeline: batch-fleet\n"
        "triggers:\n  schedules:\n    - { code: by-api, cron: '0 3 * * *' }\n",
    )

    async with session_scope(sessions) as session:
        removed = await delete_absent_trigger_documents(session, {"something-else"})

    assert removed == ["fleet-clocks"]
    assert await codes(sessions) == {"inline-nightly": None, "by-api": "hand-clocks"}


async def test_a_prune_dry_run_names_what_it_would_delete_and_deletes_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await apply(sessions, services, PIPELINE)
    await apply(sessions, services, TRIGGERS, provenance=Provenance(source=ProvenanceSource.DIRECTORY, ref="a.yaml"))

    async with session_scope(sessions) as session:
        assert await delete_absent_trigger_documents(session, set(), dry_run=True) == ["fleet-clocks"]

    async with session_scope(sessions) as session:
        assert await find_trigger_document(session, "fleet-clocks") is not None
