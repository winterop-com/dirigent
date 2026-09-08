"""What ``pipelines.apply`` accepts: a mapping, a path, or the document's own text."""

from pathlib import Path

import pytest

from clientsupport import Recorder, client_of, ok
from dirigent_client import DirigentError, ProvenanceSource
from dirigent_client.resources.pipelines import read_document

DOCUMENT = "format: dirigent/v1\nkind: pipeline\ncode: demo\nsteps: {}\n"

PLAN = {"plan": {"code": "demo", "action": "create", "digest": "sha256:abc"}}


def test_a_mapping_is_taken_as_it_stands() -> None:
    parsed, source, ref = read_document({"code": "demo"})
    assert parsed == {"code": "demo"}
    assert source is ProvenanceSource.API
    assert ref is None


def test_a_path_is_read_from_disk_and_recorded_as_its_provenance(tmp_path: Path) -> None:
    path = tmp_path / "demo.yaml"
    path.write_text(DOCUMENT)
    parsed, source, ref = read_document(path)
    assert parsed["code"] == "demo"
    assert source is ProvenanceSource.FILE
    assert ref == str(path)


def test_a_string_naming_an_existing_file_is_read_from_disk(tmp_path: Path) -> None:
    path = tmp_path / "demo.yaml"
    path.write_text(DOCUMENT)
    parsed, source, ref = read_document(str(path))
    assert parsed["code"] == "demo"
    assert source is ProvenanceSource.FILE
    assert ref == str(path)


def test_a_string_that_is_the_document_itself_is_parsed_as_yaml() -> None:
    parsed, source, ref = read_document(DOCUMENT)
    assert parsed["code"] == "demo"
    assert source is ProvenanceSource.API
    assert ref is None


def test_text_that_is_not_yaml_is_refused_before_anything_is_sent() -> None:
    with pytest.raises(DirigentError, match="not valid YAML"):
        read_document("name: [unclosed\n")


def test_a_document_that_is_not_a_mapping_is_refused() -> None:
    with pytest.raises(DirigentError, match="a document is a mapping"):
        read_document("- one\n- two\n")


async def test_a_caller_may_override_the_provenance_the_source_implies(tmp_path: Path) -> None:
    path = tmp_path / "demo.yaml"
    path.write_text(DOCUMENT)
    recorder = Recorder([ok(PLAN)])
    async with client_of(recorder) as dg:
        await dg.pipelines.apply(path, source=ProvenanceSource.UI, source_ref="the builder", code="recoded")
    assert recorder.last[3]["source"] == "ui"
    assert recorder.last[3]["source_ref"] == "the builder"
    assert recorder.last[3]["code"] == "recoded"


async def test_a_dry_run_says_so_in_the_query_string() -> None:
    recorder = Recorder([ok(PLAN)])
    async with client_of(recorder) as dg:
        result = await dg.pipelines.apply(DOCUMENT, dry_run=True)
    assert recorder.last[2] == "dry_run=true"
    assert result.plan.ok is True
