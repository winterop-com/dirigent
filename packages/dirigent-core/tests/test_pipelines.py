"""Apply, export, and retire: what the definition lifecycle does to the instance."""

from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import ProvenanceSource, RunStatus
from dirigent_core.database import session_scope
from dirigent_core.documents import load_pipeline_text as load_text
from dirigent_core.documents import to_yaml
from dirigent_core.engine import Attribution, Provenance, create_run
from dirigent_core.engine.services import EngineServices
from dirigent_core.models import ArtifactRef, LogEntry, Run, StepAttempt
from dirigent_core.pipelines import (
    PipelineInUse,
    PlanAction,
    UnknownPipeline,
    apply_document,
    delete_pipeline,
    export_pipeline,
    find_pipeline,
    get_version,
    list_pipelines,
    list_versions,
    plan_apply,
    set_active,
)

DOCUMENT = """
format: dirigent/v1
code: daily-load
description: A small pipeline.
steps:
  first:
    block: test.echo
    config: { value: one }
  second:
    block: test.echo
    depends_on: [first]
    config: { value: two }
"""


async def apply(
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    text: str,
    *,
    dry_run: bool = False,
    provenance: Provenance | None = None,
) -> object:
    async with session_scope(sessions) as session:
        return await apply_document(session, services, load_text(text), dry_run=dry_run, provenance=provenance)


async def test_a_first_apply_creates_the_pipeline_at_version_one(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(DOCUMENT))
    assert result.plan.action is PlanAction.CREATE
    assert result.version == 1
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        assert pipeline.current_version == 1


async def test_applying_the_same_document_again_is_a_reported_no_op(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(DOCUMENT))
    async with session_scope(sessions) as session:
        again = await apply_document(session, services, load_text(DOCUMENT))
    assert again.plan.action is PlanAction.UNCHANGED
    assert again.version == 1
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        assert len(await list_versions(session, pipeline.id)) == 1


async def test_a_changed_document_writes_the_next_version_with_a_diff(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(DOCUMENT))
    changed = DOCUMENT.replace("value: two", "value: TWO") + "    retry: { max_attempts: 3 }\n"
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(changed))
    assert result.plan.action is PlanAction.UPDATE
    assert result.version == 2
    assert result.plan.diff is not None
    assert result.plan.diff.steps_changed == ["second"]
    assert not result.plan.diff.steps_added


def test_a_diff_notices_added_and_removed_steps() -> None:
    before = load_text(DOCUMENT)
    after = load_text(DOCUMENT.replace("  second:", "  third:").replace("depends_on: [first]", "depends_on: [first]"))
    from dirigent_core.pipelines import diff_definitions

    diff = diff_definitions(before, after)
    assert diff.steps_added == ["third"]
    assert diff.steps_removed == ["second"]
    assert not diff.empty


async def test_a_dry_run_reports_the_plan_and_writes_nothing(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(DOCUMENT), dry_run=True)
    assert result.dry_run and result.plan.action is PlanAction.CREATE and result.version is None
    async with session_scope(sessions) as session:
        assert await find_pipeline(session, "daily-load") is None


async def test_an_invalid_document_is_refused_with_its_issues(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(DOCUMENT.replace("test.echo", "nope.gone")))
    assert result.plan.action is PlanAction.INVALID
    assert not result.plan.ok
    assert len(result.plan.issues) == 2
    async with session_scope(sessions) as session:
        assert await find_pipeline(session, "daily-load") is None


async def test_a_block_that_refuses_its_own_config_stops_the_apply(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """The apply path is where a person meets check_config: a bad program never becomes a version."""
    document = (
        "format: dirigent/v1\ncode: recase\nsteps:\n"
        "  a: { block: transform.upper, config: {input: ada, program: sideways} }\n"
    )
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(document))
    assert result.plan.action is PlanAction.INVALID
    assert [issue.location for issue in result.plan.issues] == ["steps.a.config"]
    assert "'sideways' is not a case" in result.plan.issues[0].message
    async with session_scope(sessions) as session:
        assert await find_pipeline(session, "recase") is None


async def test_provenance_is_recorded_per_version(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(
            session,
            services,
            load_text(DOCUMENT),
            provenance=Provenance(source=ProvenanceSource.FILE, ref="daily-load.yaml", applied_by="admin"),
        )
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        version = await get_version(session, pipeline)
        assert version.provenance_source is ProvenanceSource.FILE
        assert version.provenance_ref == "daily-load.yaml"
        assert version.applied_by == "admin"


async def test_export_returns_the_canonical_yaml_of_the_current_version(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(DOCUMENT))
    async with session_scope(sessions) as session:
        exported = await export_pipeline(session, "daily-load")
    assert exported == to_yaml(load_text(DOCUMENT))


async def test_export_can_name_an_older_version(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(DOCUMENT))
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(DOCUMENT.replace("value: two", "value: TWO")))
    async with session_scope(sessions) as session:
        assert "value: two" in await export_pipeline(session, "daily-load", version=1)
        assert "value: TWO" in await export_pipeline(session, "daily-load", version=2)


async def test_export_refuses_a_name_this_instance_does_not_have(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with session_scope(sessions) as session:
        with pytest.raises(UnknownPipeline):
            await export_pipeline(session, "nobody-home")


async def test_a_pipeline_can_be_deactivated_and_activated_again(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(DOCUMENT))
    async with session_scope(sessions) as session:
        assert (await set_active(session, "daily-load", active=False)).active is False
    async with session_scope(sessions) as session:
        assert (await set_active(session, "daily-load", active=True)).active is True


async def test_deleting_a_pipeline_with_no_runs_removes_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(DOCUMENT))
    async with session_scope(sessions) as session:
        await delete_pipeline(session, "daily-load")
    async with session_scope(sessions) as session:
        assert await list_pipelines(session) == []


async def settled_run(sessions: async_sessionmaker[AsyncSession], services: EngineServices) -> UUID:
    """Apply the document, run it once, and settle that run, with a log line and an artifact on it."""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(DOCUMENT))
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        run = await create_run(session, services, await get_version(session, pipeline), attribution=Attribution())
        assert run is not None
        run.status = RunStatus.SUCCEEDED
        session.add(LogEntry(run_id=run.id, step_name="first", message="one"))
        session.add(ArtifactRef(run_id=run.id, step_name="first", uri="file:///one.json"))
        return run.id


async def counted(session: AsyncSession, entity: type[ArtifactRef | LogEntry | Run | StepAttempt]) -> int:
    """Count every row of a table, whichever pipeline it belongs to."""
    found = await session.execute(sa.select(sa.func.count()).select_from(entity))
    return int(found.scalar_one())


async def test_deleting_a_pipeline_takes_its_settled_history_with_it(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await settled_run(sessions, services)
    async with session_scope(sessions) as session:
        assert await counted(session, StepAttempt) > 0, "the run must have left attempts to cascade"
    async with session_scope(sessions) as session:
        await delete_pipeline(session, "daily-load")
    async with session_scope(sessions) as session:
        assert await list_pipelines(session) == []
        for entity in (Run, StepAttempt, LogEntry, ArtifactRef):
            assert await counted(session, entity) == 0, f"{entity.__tablename__} kept a row of a deleted pipeline"


async def test_deleting_refuses_while_a_run_is_in_flight(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(DOCUMENT))
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        await create_run(session, services, await get_version(session, pipeline), attribution=Attribution())
    async with session_scope(sessions) as session:
        with pytest.raises(PipelineInUse, match="in flight"):
            await delete_pipeline(session, "daily-load")
    async with session_scope(sessions) as session:
        assert len(await list_pipelines(session)) == 1, "a refused delete leaves the pipeline alone"
        assert await counted(session, Run) == 1


async def test_deleting_frees_the_code_for_a_fresh_apply(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await settled_run(sessions, services)
    async with session_scope(sessions) as session:
        await delete_pipeline(session, "daily-load")
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(DOCUMENT))
    assert result.plan.action is PlanAction.CREATE
    assert result.version == 1


async def test_a_plan_can_be_asked_for_without_applying(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        plan = await plan_apply(session, services, load_text(DOCUMENT))
    assert plan.action is PlanAction.CREATE and plan.next_version == 1 and plan.ok


#: Three documents with overlapping vocabularies, which is what makes a repeated tag mean and.
TAGGED = {
    "climate-load": ["climate", "http"],
    "climate-shape": ["climate", "transform"],
    "org-units": ["dhis2", "http"],
}


def tagged(code: str, tags: list[str]) -> str:
    """A one-step document coded and tagged as asked."""
    rendered = ", ".join(tags)
    return (
        f"format: dirigent/v1\ncode: {code}\ndescription: A tagged pipeline.\n"
        f"tags: [{rendered}]\nsteps:\n  first:\n    block: test.echo\n    config: {{ value: one }}\n"
    )


async def assert_the_tag_filter_narrows_by_containment(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Apply three tagged documents and read them back, on whichever dialect is bound.

    Both lanes call this: the filter forks on the dialect, so proving it on SQLite proves
    only half of it.
    """
    async with session_scope(sessions) as session:
        for code, tags in TAGGED.items():
            await apply_document(session, services, load_text(tagged(code, tags)))

    async def codes(*tags: str) -> list[str]:
        async with session_scope(sessions) as session:
            return [row.code for row in await list_pipelines(session, tags=tags)]

    assert await codes() == ["climate-load", "climate-shape", "org-units"]
    assert await codes("climate") == ["climate-load", "climate-shape"]
    assert await codes("http") == ["climate-load", "org-units"]
    assert await codes("climate", "http") == ["climate-load"], "a repeated tag narrows rather than widens"
    assert await codes("climate", "dhis2") == [], "no pipeline wears both"
    assert await codes("clim") == [], "a tag matches whole or not at all"
    assert await codes("nobody-uses-this") == []


async def test_the_tag_filter_narrows_by_containment(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    await assert_the_tag_filter_narrows_by_containment(sessions, services)


async def test_applying_replaces_the_tags_a_document_declares(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Tags belong to the document, so a second apply says what they are now, not what to add."""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(tagged("relabelled", ["climate", "http"])))
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "relabelled")
        assert pipeline is not None
        assert pipeline.tags == ["climate", "http"]
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(tagged("relabelled", ["dhis2"])))
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "relabelled")
        assert pipeline is not None
        assert pipeline.tags == ["dhis2"], "the whole list is replaced, not merged"


async def test_a_document_declaring_no_tags_leaves_the_pipeline_wearing_none(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(DOCUMENT))
        pipeline = await find_pipeline(session, "daily-load")
        assert pipeline is not None
        assert pipeline.tags == []


async def test_changing_only_the_tags_is_an_update_the_plan_calls_a_settings_change(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Tags ride the canonical document, so relabelling shifts the digest like any other edit."""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(tagged("relabelled", ["climate"])))
    async with session_scope(sessions) as session:
        result = await apply_document(session, services, load_text(tagged("relabelled", ["climate", "http"])))
    assert result.plan.action is PlanAction.UPDATE
    assert result.plan.diff is not None
    assert result.plan.diff.settings_changed is True
    assert result.plan.diff.steps_changed == []


async def test_an_apply_stores_the_lowercased_tag_and_the_filter_finds_it_there(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A tag is normalised once, at apply, so the listing compares exactly from then on."""
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(tagged("shouted", ["Climate", "DHIS2"])))
    async with session_scope(sessions) as session:
        pipeline = await find_pipeline(session, "shouted")
        assert pipeline is not None
        assert pipeline.tags == ["climate", "dhis2"]
    async with session_scope(sessions) as session:
        assert [row.code for row in await list_pipelines(session, tags=["climate"])] == ["shouted"]
        assert await list_pipelines(session, tags=["Climate"]) == [], "the stored spelling is the only one"


async def test_the_canonical_export_carries_the_tags_back(
    sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    async with session_scope(sessions) as session:
        await apply_document(session, services, load_text(tagged("exported", ["climate", "http"])))
    async with session_scope(sessions) as session:
        exported = await export_pipeline(session, "exported")
    assert load_text(exported).tags == ["climate", "http"]
