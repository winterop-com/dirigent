"""``GET /schema/document``: the document format composed with this instance's catalog."""

from typing import Any, cast

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, ValidationError

from dirigent_client.schemas import Catalog
from dirigent_common import TEMPLATE_MEDIA_TYPE
from dirigent_core.documentschema import DIALECT, document_schema
from dirigent_core.plugins import load_plugin_host

PREFIX = "/api/v1"
PATH = f"{PREFIX}/schema/document"

#: A block every instance ships, whose config has a required field and a closed object.
BLOCK = "convert.std"

#: One valid config for that block, which several documents in these tests carry.
CONVERT_CONFIG = {"source": "file://in.json", "target": "file://out.yaml", "from": "json", "to": "yaml"}


def read(client: TestClient) -> dict[str, Any]:
    """Read the schema, insisting the route answered with one."""
    response = client.get(PATH)
    assert response.status_code == 200, response.text
    return cast("dict[str, Any]", response.json())


def branch(schema: dict[str, Any], kind: str) -> dict[str, Any]:
    """One of the two document kinds the schema offers, picked by its ``kind`` constant."""
    options = cast("list[dict[str, Any]]", schema["oneOf"])
    matched = [one for one in options if one["properties"]["kind"]["const"] == kind]
    assert len(matched) == 1, f"no single branch for {kind}"
    return matched[0]


def deepest(errors: Any) -> list[ValidationError]:
    """The leaf errors of a validation: what each ``oneOf`` branch itself complained about."""
    found: list[ValidationError] = []
    for error in cast("list[ValidationError]", list(errors)):
        inner = deepest(error.context or [])
        found.extend(inner or [error])
    return found


def deep_messages(errors: Any) -> list[str]:
    """Every message a validation produced, including the ones inside a ``oneOf`` branch."""
    return [error.message for error in deepest(errors)]


def case_for(schema: dict[str, Any], block_id: str) -> dict[str, Any]:
    """The ``if``/``then`` case a step gets for one block."""
    cases = cast("list[dict[str, Any]]", schema["$defs"]["StepDefinition"]["allOf"])
    matched = [case for case in cases if case["if"]["properties"]["block"]["const"] == block_id]
    assert len(matched) == 1, f"no single case for {block_id}"
    return matched[0]


def test_the_schema_is_itself_valid_draft_2020_12(client: TestClient) -> None:
    schema = read(client)
    assert schema["$schema"] == DIALECT
    Draft202012Validator.check_schema(schema)


def test_a_step_config_is_the_named_block_own_schema(client: TestClient) -> None:
    config = case_for(read(client), BLOCK)["then"]["properties"]["config"]
    assert config["additionalProperties"] is False
    assert set(config["required"]) == {"source", "target", "from", "to"}
    assert config["properties"]["from"]["type"] == "string"


def test_every_installed_block_gets_a_case_and_the_step_enumerates_them(client: TestClient) -> None:
    schema = read(client)
    installed = {entry.id for entry in load_plugin_host().catalog().blocks}
    cases = cast("list[dict[str, Any]]", schema["$defs"]["StepDefinition"]["allOf"])
    assert {case["if"]["properties"]["block"]["const"] for case in cases} == installed
    assert set(schema["$defs"]["StepDefinition"]["properties"]["block"]["enum"]) == installed


def test_a_block_own_definitions_are_lifted_under_names_only_it_uses(client: TestClient) -> None:
    # Several blocks contribute a `Size`, and a shared `$defs` has room for one of them.
    schema = read(client)
    config = case_for(schema, "storage.read")["then"]["properties"]["config"]
    assert "$defs" not in config
    assert config["properties"]["max_size"]["$ref"] == "#/$defs/storage.read.Size"
    assert "storage.read.Size" in schema["$defs"]


def test_the_schema_accepts_a_document_and_refuses_a_config_key_no_block_takes(client: TestClient) -> None:
    validator = Draft202012Validator(read(client))
    document = {
        "format": "dirigent/v1",
        "kind": "pipeline",
        "code": "convert-one",
        "steps": {"parse": {"block": BLOCK, "config": dict(CONVERT_CONFIG)}},
    }
    assert list(validator.iter_errors(document)) == []  # pyright: ignore[reportUnknownMemberType]

    steps = cast("dict[str, Any]", document["steps"])
    cast("dict[str, Any]", steps["parse"]["config"])["nonsense"] = 1
    problems = deep_messages(validator.iter_errors(document))  # pyright: ignore[reportUnknownMemberType]
    assert problems, "an unknown config key was accepted"
    assert any("nonsense" in message for message in problems)


def test_the_schema_squiggles_a_tag_the_format_would_refuse(client: TestClient) -> None:
    """The grammar is checked at apply; an editor gets to say so before the apply happens."""
    validator = Draft202012Validator(read(client))
    document = {
        "format": "dirigent/v1",
        "kind": "pipeline",
        "code": "labelled",
        "tags": ["climate", "Bad Tag"],
        "steps": {"parse": {"block": BLOCK, "config": dict(CONVERT_CONFIG)}},
    }
    # The other branch fails on `kind` alone, which is how the two are told apart at all.
    paths = [list(problem.absolute_path) for problem in deepest(validator.iter_errors(document))]  # pyright: ignore[reportUnknownMemberType]
    assert ["tags", 1] in paths, paths

    document["tags"] = ["climate", "http"]
    assert list(validator.iter_errors(document)) == []  # pyright: ignore[reportUnknownMemberType]


def test_the_schema_accepts_a_triggers_document_too(client: TestClient) -> None:
    """The editor squiggles both kinds, and picks between them by ``kind``."""
    validator = Draft202012Validator(read(client))
    document: dict[str, Any] = {
        "format": "dirigent/v1",
        "kind": "triggers",
        "code": "nightly-clocks",
        "pipeline": "convert-one",
        "triggers": {"schedules": [{"code": "nightly", "cron": "0 5 * * *"}]},
    }
    assert list(validator.iter_errors(document)) == []  # pyright: ignore[reportUnknownMemberType]

    document["steps"] = {}
    problems = deep_messages(validator.iter_errors(document))  # pyright: ignore[reportUnknownMemberType]
    assert any("steps" in message for message in problems), "a triggers document declares no steps"


def test_a_triggers_document_must_name_a_pipeline(client: TestClient) -> None:
    validator = Draft202012Validator(read(client))
    document = {"format": "dirigent/v1", "kind": "triggers", "code": "clocks"}
    problems = deep_messages(validator.iter_errors(document))  # pyright: ignore[reportUnknownMemberType]
    assert any("pipeline" in message for message in problems)


def test_an_operator_may_read_it_too(operator: TestClient) -> None:
    assert operator.get(PATH).status_code == 200


def test_an_anonymous_request_is_refused_like_every_other_read(anonymous: TestClient) -> None:
    assert anonymous.get(PATH).status_code == 401


def test_an_instance_with_no_blocks_composes_the_format_alone() -> None:
    schema = document_schema(Catalog())
    Draft202012Validator.check_schema(schema)
    assert "allOf" not in schema["$defs"]["StepDefinition"]
    assert "enum" not in schema["$defs"]["StepDefinition"]["properties"]["block"]


def test_the_schema_offers_exactly_the_two_document_kinds(client: TestClient) -> None:
    schema = read(client)
    options = cast("list[dict[str, Any]]", schema["oneOf"])
    assert [one["properties"]["kind"]["const"] for one in options] == ["pipeline", "triggers"]
    assert "steps" in branch(schema, "pipeline")["properties"]
    assert "pipeline" in branch(schema, "triggers")["properties"]


def test_the_report_template_is_published_as_the_program_it_is(client: TestClient) -> None:
    """An editor colours the field by its media type, so the schema has to carry one."""
    schema = read(client)
    pipeline = branch(schema, "pipeline")
    assert "report" in pipeline["properties"]
    report = cast("dict[str, Any]", schema["$defs"]["ReportSpec"])
    assert report["properties"]["template"]["contentMediaType"] == TEMPLATE_MEDIA_TYPE


def test_a_document_declaring_a_report_validates_against_the_published_schema(client: TestClient) -> None:
    validator = Draft202012Validator(read(client))
    document = {
        "format": "dirigent/v1",
        "kind": "pipeline",
        "code": "reported",
        "steps": {"parse": {"block": BLOCK, "config": dict(CONVERT_CONFIG)}},
        "report": {"template": "# {{ run.status }}"},
    }
    assert validator.is_valid(document), deep_messages(validator.iter_errors(document))  # pyright: ignore[reportUnknownMemberType]
