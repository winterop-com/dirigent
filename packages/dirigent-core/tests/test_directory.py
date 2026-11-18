"""Applying a directory of documents: the walk, its refusals, and the prune behind it."""

from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dirigent_client.enums import ProvenanceSource
from dirigent_core.database import session_scope
from dirigent_core.directory import apply_directory
from dirigent_core.documents import discover_documents, load_text
from dirigent_core.engine import EngineServices
from dirigent_core.engine.runs import Provenance
from dirigent_core.pipelines import apply_document, find_pipeline, get_version, require_pipeline, set_active
from dirigent_core.schemas import find_schema
from dirigent_core.trigger_documents import list_trigger_documents

DOCUMENT = """
format: dirigent/v1
code: {code}
steps:
  only:
    block: test.echo
    config: {{ value: {value} }}
"""


def write(root: Path, name: str, *, code: str, value: str = "one") -> Path:
    """Write one document into the directory."""
    path = root / name
    path.write_text(DOCUMENT.format(code=code, value=value))
    return path


async def active_of(sessions: async_sessionmaker[AsyncSession], code: str) -> bool:
    async with session_scope(sessions) as session:
        return (await require_pipeline(session, code)).active


async def pruned_of(sessions: async_sessionmaker[AsyncSession], code: str) -> bool:
    async with session_scope(sessions) as session:
        return (await require_pipeline(session, code)).pruned


async def test_a_fresh_directory_seeds_every_document(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "a.yaml", code="first")
    write(tmp_path, "b.yaml", code="second")

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.applied == ["first", "second"]
    assert summary.refused == []
    async with session_scope(sessions) as session:
        stored = await require_pipeline(session, "first")
        version = await get_version(session, stored)
        assert version.provenance_source is ProvenanceSource.DIRECTORY
        assert version.provenance_ref == "a.yaml"


async def test_a_changed_document_updates_and_an_unchanged_one_is_a_no_op(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "a.yaml", code="first")
    write(tmp_path, "b.yaml", code="second")
    await apply_directory(sessions, services, tmp_path)
    write(tmp_path, "a.yaml", code="first", value="two")

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.updated == ["first"]
    assert summary.unchanged == ["second"]
    assert summary.applied == []


async def test_a_refused_document_never_stops_the_walk(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    (tmp_path / "1-broken.yaml").write_text(DOCUMENT.format(code="broken", value="x").replace("test.echo", "no.such"))
    (tmp_path / "2-torn.yaml").write_text("{ not a document")
    write(tmp_path, "3-good.yaml", code="good")

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.applied == ["good"]
    assert [refused.path for refused in summary.refused] == ["1-broken.yaml", "2-torn.yaml"]
    assert summary.refused[0].code == "broken"
    assert summary.refused[1].code is None


async def test_a_document_carrying_its_own_connections_is_refused(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    text = DOCUMENT.format(code="carried", value="one") + (
        "connections:\n  somewhere:\n    kind: http\n    config: { base_url: http://x.test }\n"
    )
    (tmp_path / "carried.yaml").write_text(text)

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.applied == []
    assert "carries its own connections" in summary.refused[0].message
    async with session_scope(sessions) as session:
        assert await find_pipeline(session, "carried") is None


async def test_a_document_carrying_its_own_schemas_is_refused(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    text = DOCUMENT.format(code="carried", value="one") + (
        "schemas:\n  reading:\n    type: object\n    properties:\n      value: { type: string }\n"
    )
    (tmp_path / "carried.yaml").write_text(text)
    write(tmp_path, "sibling.yaml", code="sibling")

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.applied == ["sibling"]
    assert [refused.path for refused in summary.refused] == ["carried.yaml"]
    assert summary.refused[0].message == (
        "this document carries its own schemas (reading), which an instance will not store: "
        "create them on the instance and let the document name them under requires.schemas"
    )
    async with session_scope(sessions) as session:
        assert await find_pipeline(session, "carried") is None


async def test_prune_deactivates_only_directory_absentees(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "gone.yaml", code="gone")
    write(tmp_path, "kept.yaml", code="kept")
    await apply_directory(sessions, services, tmp_path)
    # A pipeline applied any other way is equally absent from the directory, and untouchable.
    async with session_scope(sessions) as session:
        await apply_document(
            session,
            services,
            load_text(DOCUMENT.format(code="authored", value="one")),
            provenance=Provenance(source=ProvenanceSource.API),
        )
    (tmp_path / "gone.yaml").unlink()

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.pruned == ["gone"]
    assert await active_of(sessions, "gone") is False
    assert await active_of(sessions, "kept") is True
    assert await active_of(sessions, "authored") is True


async def test_a_refused_document_still_counts_as_present_for_prune(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "a.yaml", code="first")
    await apply_directory(sessions, services, tmp_path)
    # The document breaks, but it is still in the directory: absence is what prunes.
    (tmp_path / "a.yaml").write_text(DOCUMENT.format(code="first", value="x").replace("test.echo", "no.such"))

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.pruned == []
    assert await active_of(sessions, "first") is True


async def test_an_empty_directory_refuses_to_prune(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "a.yaml", code="first")
    await apply_directory(sessions, services, tmp_path)
    (tmp_path / "a.yaml").unlink()

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.pruned == []
    assert summary.prune_refusal is not None
    assert await active_of(sessions, "first") is True


async def test_a_dry_run_reports_the_prune_and_writes_nothing(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "gone.yaml", code="gone")
    write(tmp_path, "kept.yaml", code="kept")
    await apply_directory(sessions, services, tmp_path)
    (tmp_path / "gone.yaml").unlink()
    write(tmp_path, "kept.yaml", code="kept", value="two")

    summary = await apply_directory(sessions, services, tmp_path, prune=True, dry_run=True)

    assert summary.pruned == ["gone"]
    assert summary.updated == ["kept"]
    assert await active_of(sessions, "gone") is True
    async with session_scope(sessions) as session:
        kept = await require_pipeline(session, "kept")
        assert kept.current_version == 1


async def test_a_missing_directory_is_a_warning_and_an_empty_summary(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    summary = await apply_directory(sessions, services, tmp_path / "nowhere", prune=True)

    assert summary.applied == []
    assert summary.pruned == []
    assert summary.prune_refusal is not None


async def test_an_instance_fault_aborts_the_walk_instead_of_refusing_everything(
    tmp_path: Path,
    sessions: async_sessionmaker[AsyncSession],
    services: EngineServices,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seen live: a schema drift refused 59 documents one by one and the log buried the fault."""
    write(tmp_path, "a.yaml", code="first")
    write(tmp_path, "b.yaml", code="second")

    async def drifted(*args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT 1", None, Exception("column does not exist"))

    monkeypatch.setattr("dirigent_core.directory.apply_document", drifted)
    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.aborted is not None
    assert "column does not exist" in summary.aborted
    assert summary.refused == []
    assert summary.applied == []


async def test_one_code_in_two_files_applies_the_first_and_refuses_the_second(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A duplicated code across a nested corpus is a mistake said out loud, not a silent update."""
    write(tmp_path, "first.yaml", code="twice-named")
    (tmp_path / "deeper").mkdir()
    write(tmp_path, "deeper/again.yaml", code="twice-named", value="two")

    summary = await apply_directory(sessions, services, tmp_path)

    # The walk is in relative-path order, so the nested spelling comes first here.
    assert summary.applied == ["twice-named"]
    assert [refusal.path for refusal in summary.refused] == ["first.yaml"]
    assert "already applied from deeper/again.yaml" in summary.refused[0].message


def test_discovery_walks_the_whole_tree_sorted_and_suffix_bound(tmp_path: Path) -> None:
    (tmp_path / "b.yaml").write_text("x")
    (tmp_path / "a.json").write_text("x")
    (tmp_path / "notes.md").write_text("x")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.yaml").write_text("x")

    found = [path.relative_to(tmp_path).as_posix() for path in discover_documents(tmp_path)]
    assert found == ["a.json", "b.yaml", "nested/c.yaml"]


#: A clock file whose name sorts before the pipeline it schedules, so only the ordering rule
#: can make the two converge in one walk.
CLOCKS = """
format: dirigent/v1
kind: triggers
code: {code}
pipeline: {pipeline}
triggers:
  schedules:
    - code: ops-nightly
      cron: "0 4 * * *"
"""


async def test_a_directory_carrying_both_kinds_converges_in_one_pass(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Pipelines are applied before triggers documents, whatever the paths sort as."""
    (tmp_path / "1-clocks.yaml").write_text(CLOCKS.format(code="fleet-clocks", pipeline="fleet"))
    write(tmp_path, "2-fleet.yaml", code="fleet")

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.refused == []
    assert sorted(summary.applied) == ["fleet", "fleet-clocks"]


async def test_a_prune_deletes_the_triggers_documents_the_directory_dropped(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "fleet.yaml", code="fleet")
    (tmp_path / "clocks.yaml").write_text(CLOCKS.format(code="fleet-clocks", pipeline="fleet"))
    await apply_directory(sessions, services, tmp_path)
    (tmp_path / "clocks.yaml").unlink()

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.trigger_documents_removed == ["fleet-clocks"]
    assert summary.pruned == []
    async with session_scope(sessions) as session:
        assert await list_trigger_documents(session) == []


async def test_a_triggers_document_may_share_its_pipelines_code(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """A pipeline and a triggers document live in separate tables, so one code names both."""
    write(tmp_path, "orders.yaml", code="orders")
    (tmp_path / "orders.triggers.yaml").write_text(CLOCKS.format(code="orders", pipeline="orders"))

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.refused == []
    assert summary.applied == ["orders", "orders"]
    assert summary.pruned == []
    assert summary.trigger_documents_removed == []
    async with session_scope(sessions) as session:
        assert [document.code for document in await list_trigger_documents(session)] == ["orders"]
    assert await active_of(sessions, "orders")


#: A plain JSON Schema, the shape a directory carries beside its documents.
SCHEMA = """
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "ou-record",
  "title": "%(title)s",
  "type": "object",
  "properties": { "id": { "type": "string" } }
}
"""

#: A pipeline that refuses to apply while the instance holds no ``ou-record`` schema.
NEEDS_SCHEMA = """
format: dirigent/v1
code: needs-a-shape
requires:
  schemas:
    - ou-record
steps:
  only:
    block: test.echo
    config: { value: one }
"""


def write_schema(root: Path, name: str, *, title: str = "OU record") -> None:
    """Write one plain JSON Schema into the directory."""
    (root / name).write_text(SCHEMA % {"title": title})


async def test_a_schema_is_stored_before_the_pipeline_that_requires_it(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    """Schemas go before the pipelines, whatever the paths sort as."""
    write_schema(tmp_path, "2-ou-record.json")
    (tmp_path / "1-needs.yaml").write_text(NEEDS_SCHEMA)

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.refused == []
    assert sorted(summary.applied) == ["needs-a-shape", "ou-record"]
    assert summary.schemas == ["ou-record"]
    async with session_scope(sessions) as session:
        assert await find_schema(session, "ou-record") is not None


async def test_an_unchanged_schema_is_a_no_op_and_an_edited_one_updates(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write_schema(tmp_path, "ou-record.json")
    await apply_directory(sessions, services, tmp_path)

    unchanged = await apply_directory(sessions, services, tmp_path)
    assert unchanged.unchanged == ["ou-record"]
    assert unchanged.applied == []

    write_schema(tmp_path, "ou-record.json", title="OU record, revised")
    updated = await apply_directory(sessions, services, tmp_path)
    assert updated.updated == ["ou-record"]
    async with session_scope(sessions) as session:
        stored = await find_schema(session, "ou-record")
        assert stored is not None
        assert stored.name == "OU record, revised"


async def test_an_invalid_schema_is_refused_and_the_pipelines_still_apply(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    (tmp_path / "broken.json").write_text(
        '{"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "nonsense"}'
    )
    write(tmp_path, "good.yaml", code="good")

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.applied == ["good"]
    assert summary.schemas == []
    assert [refusal.path for refusal in summary.refused] == ["broken.json"]
    assert "not a valid JSON Schema" in summary.refused[0].message


async def test_a_file_that_is_not_utf8_is_refused_and_the_walk_goes_on(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    (tmp_path / "1-latin.yaml").write_bytes(DOCUMENT.format(code="latin", value="caf\u00e9").encode("latin-1"))
    write(tmp_path, "2-good.yaml", code="good")

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.applied == ["good"]
    assert [refusal.path for refusal in summary.refused] == ["1-latin.yaml"]
    assert summary.aborted is None


async def test_two_schema_files_of_one_code_store_the_first_and_refuse_the_second(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write_schema(tmp_path, "a.json", title="First")
    write_schema(tmp_path, "b.json", title="Second")
    await apply_directory(sessions, services, tmp_path)

    again = await apply_directory(sessions, services, tmp_path)

    assert again.unchanged == ["ou-record"]
    assert again.updated == []
    assert [(refusal.path, refusal.code) for refusal in again.refused] == [("b.json", "ou-record")]
    async with session_scope(sessions) as session:
        stored = await find_schema(session, "ou-record")
        assert stored is not None
        assert stored.name == "First"


async def test_a_schema_title_longer_than_its_column_is_refused_and_the_walk_goes_on(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write_schema(tmp_path, "long.json", title="x" * 201)
    write(tmp_path, "good.yaml", code="good")

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.applied == ["good"]
    assert summary.schemas == []
    assert [refusal.path for refusal in summary.refused] == ["long.json"]
    assert "at most 200 characters" in summary.refused[0].message


async def test_a_json_file_declaring_the_format_is_still_a_document(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    (tmp_path / "a.json").write_text(
        '{"format": "dirigent/v1", "code": "written-as-json",'
        ' "steps": {"only": {"block": "test.echo", "config": {"value": "one"}}}}'
    )

    summary = await apply_directory(sessions, services, tmp_path)

    assert summary.applied == ["written-as-json"]
    assert summary.schemas == []


async def test_a_dry_run_reports_a_schema_and_stores_nothing(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write_schema(tmp_path, "ou-record.json")

    summary = await apply_directory(sessions, services, tmp_path, dry_run=True)

    assert summary.applied == ["ou-record"]
    assert summary.schemas == ["ou-record"]
    async with session_scope(sessions) as session:
        assert await find_schema(session, "ou-record") is None


async def test_a_prune_leaves_a_schema_alone_and_keeps_its_code_out_of_the_pipelines(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write_schema(tmp_path, "ou-record.json")
    write(tmp_path, "kept.yaml", code="kept")

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.pruned == []
    assert summary.schemas == ["ou-record"]
    async with session_scope(sessions) as session:
        assert await find_schema(session, "ou-record") is not None


async def test_a_prune_keeps_a_document_nested_in_a_subdirectory(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "top.yaml", code="top")
    (tmp_path / "team-a").mkdir()
    write(tmp_path, "team-a/nightly.yaml", code="nightly")
    await apply_directory(sessions, services, tmp_path)

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.unchanged == ["nightly", "top"]
    assert summary.pruned == []
    assert summary.prune_refusal is None
    assert await active_of(sessions, "nightly") is True


#: Ways a present pipeline's file can fail to load, each written over a document that applied.
UNLOADABLE = {
    "an unknown key": DOCUMENT.format(code="orders", value="one") + "tagz: [nightly]\n",
    "a YAML syntax error": "format: dirigent/v1\ncode: orders\nsteps: [unclosed\n",
}


@pytest.mark.parametrize("broken", UNLOADABLE.values(), ids=list(UNLOADABLE))
async def test_a_present_document_that_fails_to_load_stops_the_prune(
    broken: str, tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "orders.yaml", code="orders")
    write(tmp_path, "kept.yaml", code="kept")
    write(tmp_path, "gone.yaml", code="gone")
    await apply_directory(sessions, services, tmp_path)
    (tmp_path / "orders.yaml").write_text(broken)
    (tmp_path / "gone.yaml").unlink()

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert [(refused.path, refused.code) for refused in summary.refused] == [("orders.yaml", None)]
    assert summary.pruned == []
    assert summary.prune_refusal is not None
    assert "orders.yaml" in summary.prune_refusal
    assert await active_of(sessions, "orders") is True
    assert await active_of(sessions, "gone") is True, "the next clean walk prunes it"


async def test_a_pipeline_sharing_a_schemas_code_is_kept_by_the_prune(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    (tmp_path / "orders.json").write_text('{"type": "object", "properties": {"id": {"type": "string"}}}')
    write(tmp_path, "orders.yaml", code="orders")

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.schemas == ["orders"]
    assert summary.pruned == []
    assert await active_of(sessions, "orders") is True


async def test_a_directory_left_with_only_schemas_refuses_to_prune(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write_schema(tmp_path, "ou-record.json")
    (tmp_path / "pipelines").mkdir()
    write(tmp_path, "pipelines/one.yaml", code="one")
    write(tmp_path, "pipelines/two.yaml", code="two")
    await apply_directory(sessions, services, tmp_path)
    for path in (tmp_path / "pipelines").iterdir():
        path.unlink()

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.pruned == []
    assert summary.prune_refusal is not None
    assert await active_of(sessions, "one") is True
    assert await active_of(sessions, "two") is True


async def test_restoring_a_pruned_document_reactivates_its_pipeline(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "kept.yaml", code="kept")
    write(tmp_path, "gone.yaml", code="gone")
    await apply_directory(sessions, services, tmp_path)
    (tmp_path / "gone.yaml").unlink()
    assert (await apply_directory(sessions, services, tmp_path, prune=True)).pruned == ["gone"]
    assert await pruned_of(sessions, "gone") is True

    write(tmp_path, "gone.yaml", code="gone")
    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.unchanged == ["gone", "kept"]
    assert summary.reactivated == ["gone"]
    assert await active_of(sessions, "gone") is True
    assert await pruned_of(sessions, "gone") is False


async def test_a_dry_run_reports_the_reactivation_and_writes_nothing(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "kept.yaml", code="kept")
    write(tmp_path, "gone.yaml", code="gone")
    await apply_directory(sessions, services, tmp_path)
    (tmp_path / "gone.yaml").unlink()
    await apply_directory(sessions, services, tmp_path, prune=True)
    write(tmp_path, "gone.yaml", code="gone")

    summary = await apply_directory(sessions, services, tmp_path, prune=True, dry_run=True)

    assert summary.reactivated == ["gone"]
    assert await active_of(sessions, "gone") is False


async def test_a_pipeline_a_person_deactivated_stays_inactive_when_its_document_is_applied(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "kept.yaml", code="kept")
    write(tmp_path, "gone.yaml", code="gone")
    await apply_directory(sessions, services, tmp_path)
    (tmp_path / "gone.yaml").unlink()
    await apply_directory(sessions, services, tmp_path, prune=True)
    async with session_scope(sessions) as session:
        await set_active(session, "gone", active=True)
        await set_active(session, "gone", active=False)
    write(tmp_path, "gone.yaml", code="gone", value="two")

    summary = await apply_directory(sessions, services, tmp_path, prune=True)

    assert summary.updated == ["gone"]
    assert summary.reactivated == []
    assert await active_of(sessions, "gone") is False


async def test_only_a_directory_apply_reactivates_a_pruned_pipeline(
    tmp_path: Path, sessions: async_sessionmaker[AsyncSession], services: EngineServices
) -> None:
    write(tmp_path, "kept.yaml", code="kept")
    write(tmp_path, "gone.yaml", code="gone")
    await apply_directory(sessions, services, tmp_path)
    (tmp_path / "gone.yaml").unlink()
    await apply_directory(sessions, services, tmp_path, prune=True)

    async with session_scope(sessions) as session:
        result = await apply_document(
            session,
            services,
            load_text(DOCUMENT.format(code="gone", value="one")),
            provenance=Provenance(source=ProvenanceSource.FILE),
        )

    assert result.reactivated is False
    assert await active_of(sessions, "gone") is False
