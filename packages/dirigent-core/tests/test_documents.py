"""The dirigent/v1 document format: parsing, canonical export, digests, catalog validation."""

import json
from datetime import timedelta
from typing import Any

import pytest

from dirigent_core.documents import (
    DocumentError,
    digest_of,
    digest_of_document,
    load_document,
    parse_text,
    summarize,
    to_yaml,
    validate_against_catalog,
)
from dirigent_core.documents import load_pipeline_text as load_text
from dirigent_core.engine.definition import PipelineDefinition, canonical_document
from dirigent_core.plugins import PluginHost, load_plugin_host
from engineblocks import EngineTestPlugin

MINIMAL = """
format: dirigent/v1
kind: pipeline
code: minimal
steps:
  only:
    block: test.echo
"""

FULL = """
format: dirigent/v1
kind: pipeline
code: daily-load
name: Daily load
description: Everything the format can say.
concurrency: skip
params:
  properties:
    day: { type: string, format: date }
    regions: { type: array, items: { type: string }, default: [east, west] }
  required: [day]
  type: object
steps:
  push:
    block: test.echo
    depends_on: [wait]
    for_each: "${params.regions}"
    items: continue
    config:
      value: "ingest ${item} for ${params.day}"
    retry: { max_attempts: 5, backoff: 45s, jitter: 0.5 }
  wait:
    name: Wait for the extract
    block: test.tick
    config: { key: "${params.day}" }
    poll: 5m
    deadline: 6h
    on_timeout: skip
  cleanup:
    block: test.echo
    depends_on: [push]
    rule: one_failed
    continue_on_failure: true
    config: { value: "cleanup" }
triggers:
  schedules:
    - code: nightly
      name: Nightly, Oslo time
      description: Fires the load once the upstream extract has settled.
      cron: "0 5 * * *"
      timezone: Europe/Oslo
      params: { day: "2026-01-01" }
  webhooks:
    - code: upstream-publish
      name: Upstream publish
      description: Called by the upstream system when the extract is published.
      params_from_payload: { day: "$.published.date" }
requires:
  blocks: [test.echo]
  connections: []
"""


@pytest.fixture
def host() -> PluginHost:
    return PluginHost({"engine-tests": EngineTestPlugin().contribute()})


def test_yaml_and_json_are_the_same_model_read_two_ways() -> None:
    from_yaml = load_text(FULL)
    as_json = json.dumps(canonical_document(from_yaml))
    assert load_text(as_json) == from_yaml


def test_a_document_must_declare_its_format() -> None:
    with pytest.raises(DocumentError, match="declares no format"):
        load_document({"kind": "pipeline", "code": "x", "steps": {}})


def test_a_future_format_is_refused_by_name_not_by_field_errors() -> None:
    with pytest.raises(DocumentError, match="dirigent/v2"):
        load_document({"format": "dirigent/v2", "code": "x", "steps": {}})


def test_only_the_pipeline_kind_exists_in_v1() -> None:
    with pytest.raises(DocumentError, match="kind"):
        load_document({"format": "dirigent/v1", "kind": "connection", "code": "x", "steps": {}})


def test_an_empty_or_non_mapping_document_says_so() -> None:
    with pytest.raises(DocumentError, match="empty"):
        parse_text("\n# nothing but a comment\n")
    with pytest.raises(DocumentError, match="mapping"):
        parse_text("- a\n- b\n")
    with pytest.raises(DocumentError, match="not valid YAML"):
        parse_text("a: [1,\n")


def test_every_problem_is_reported_at_once_not_one_at_a_time() -> None:
    with pytest.raises(DocumentError) as raised:
        load_text("format: dirigent/v1\ncode: 'Bad Name'\nsteps: {}\n")
    assert len(raised.value.problems) >= 2


def test_the_canonical_export_round_trips_byte_identically() -> None:
    exported = to_yaml(load_text(FULL))
    assert to_yaml(load_text(exported)) == exported


def test_the_canonical_export_does_not_depend_on_the_order_things_were_written_in() -> None:
    shuffled = FULL.replace(
        "steps:\n  push:", "steps:\n  zzz_unused:\n    block: test.echo\n    config: { value: z }\n  push:"
    )
    reordered = load_text(shuffled)
    assert "zzz_unused" in to_yaml(reordered)
    document = canonical_document(reordered)
    assert list(document) == [
        "format",
        "kind",
        "code",
        "name",
        "description",
        "concurrency",
        "params",
        "steps",
        "triggers",
        "requires",
    ]


def test_steps_export_in_topological_order_so_a_document_reads_downward() -> None:
    document = canonical_document(load_text(FULL))
    steps: Any = document["steps"]
    assert list(steps) == ["wait", "push", "cleanup"]


def test_defaults_are_omitted_so_a_small_pipeline_stays_small() -> None:
    exported = to_yaml(load_text(MINIMAL))
    assert exported == "format: dirigent/v1\nkind: pipeline\ncode: minimal\nsteps:\n  only:\n    block: test.echo\n"


def test_durations_come_back_out_in_the_humane_form() -> None:
    exported = to_yaml(load_text(FULL))
    assert "poll: 5m" in exported
    assert "deadline: 6h" in exported
    assert "backoff: 45s" in exported


def test_the_digest_is_a_function_of_content_not_of_spelling() -> None:
    one = load_text(FULL)
    two = load_text(to_yaml(one))
    assert digest_of(one) == digest_of(two)
    assert digest_of_document(canonical_document(one)) == digest_of(one)


def test_a_changed_document_changes_its_digest() -> None:
    before = load_text(MINIMAL)
    after = load_text(MINIMAL.replace("test.echo", "test.fail"))
    assert digest_of(before) != digest_of(after)


def test_a_stored_document_whose_keys_were_reordered_still_exports_identically() -> None:
    definition = load_text(FULL)
    stored = canonical_document(definition)
    scrambled = {key: stored[key] for key in sorted(stored, reverse=True)}
    assert to_yaml(load_document(scrambled)) == to_yaml(definition)


def test_triggers_and_requires_travel_with_the_document() -> None:
    definition = load_text(FULL)
    assert [schedule.code for schedule in definition.triggers.schedules] == ["nightly"]
    assert definition.triggers.schedules[0].timezone == "Europe/Oslo"
    assert [webhook.code for webhook in definition.triggers.webhooks] == ["upstream-publish"]
    assert definition.requires.blocks == ["test.echo"]


def test_a_schedule_declares_exactly_one_clock() -> None:
    with pytest.raises(DocumentError, match="exactly one"):
        load_text(MINIMAL + "triggers:\n  schedules:\n    - code: n\n      cron: '* * * * *'\n      interval: 5m\n")
    with pytest.raises(DocumentError, match="exactly one"):
        load_text(MINIMAL + "triggers:\n  schedules:\n    - code: n\n")


def test_two_schedules_may_not_share_a_code() -> None:
    with pytest.raises(DocumentError, match="duplicate schedule"):
        load_text(
            MINIMAL + "triggers:\n  schedules:\n    - {code: n, cron: '* * * * *'}\n    - {code: n, interval: 5m}\n"
        )


def test_a_cycle_is_refused_at_apply_time(host: PluginHost) -> None:
    with pytest.raises(DocumentError, match="cycle"):
        load_text(
            "format: dirigent/v1\ncode: looped\nsteps:\n"
            "  a: { block: test.echo, depends_on: [b] }\n"
            "  b: { block: test.echo, depends_on: [a] }\n"
        )


def test_an_unknown_dependency_is_refused() -> None:
    with pytest.raises(DocumentError, match="unknown step"):
        load_text("format: dirigent/v1\ncode: dangling\nsteps:\n  a: { block: test.echo, depends_on: [nope] }\n")


@pytest.mark.parametrize(
    ("declared", "problem"),
    [
        ("[ok, 'Bad Tag']", "tags: Value error, tags[1] 'Bad Tag' is not a valid tag"),
        ("[climate, climate]", "tags: Value error, tags[1] 'climate' is declared twice"),
    ],
    ids=["not-a-tag", "said-twice"],
)
def test_a_tag_a_document_may_not_wear_is_refused_at_the_place_it_was_written(declared: str, problem: str) -> None:
    with pytest.raises(DocumentError) as raised:
        load_text(f"format: dirigent/v1\ncode: labelled\ntags: {declared}\nsteps:\n  a: {{ block: test.echo }}\n")
    assert raised.value.problems[0].startswith(problem)


def test_a_document_wearing_too_many_tags_is_refused_by_the_count() -> None:
    crowd = ", ".join(f"tag-{index}" for index in range(17))
    with pytest.raises(DocumentError, match="at most 16 tags, and this one declares 17"):
        load_text(f"format: dirigent/v1\ncode: labelled\ntags: [{crowd}]\nsteps:\n  a: {{ block: test.echo }}\n")


def test_a_misspelled_step_key_is_refused_and_the_right_one_is_named() -> None:
    """A silently ignored ``depend_on`` would delete an edge and leave the digest unchanged."""
    with pytest.raises(DocumentError) as raised:
        load_text(
            "format: dirigent/v1\ncode: typo\nsteps:\n"
            "  a: { block: test.echo }\n"
            "  b: { block: test.echo, depend_on: [a] }\n"
        )
    assert raised.value.problems == ["steps.b.depend_on: unknown key (did you mean 'depends_on'?)"]


@pytest.mark.parametrize(
    ("document", "problem"),
    [
        (
            "format: dirigent/v1\ncode: typo\ndescripton: oops\nsteps:\n  a: { block: test.echo }\n",
            "descripton: unknown key (did you mean 'description'?)",
        ),
        (
            "format: dirigent/v1\ncode: typo\nsteps:\n  a: { block: test.echo, retry: { max_attemps: 3 } }\n",
            "steps.a.retry.max_attemps: unknown key (did you mean 'max_attempts'?)",
        ),
        (
            "format: dirigent/v1\ncode: typo\nsteps:\n  a: { block: test.echo }\n"
            "triggers:\n  schedules:\n    - { code: n, cron: '* * * * *', timezon: UTC }\n",
            "triggers.schedules.0.timezon: unknown key (did you mean 'timezone'?)",
        ),
        (
            "format: dirigent/v1\ncode: typo\nsteps:\n  a: { block: test.echo, wibble: 1 }\n",
            "steps.a.wibble: unknown key",
        ),
    ],
)
def test_a_key_the_format_does_not_define_is_refused_wherever_it_is_written(document: str, problem: str) -> None:
    with pytest.raises(DocumentError) as raised:
        load_text(document)
    assert raised.value.problems == [problem]


def test_a_misspelled_key_is_refused_rather_than_digesting_as_if_it_were_not_there() -> None:
    """Ignoring it would make the typo and the corrected document indistinguishable."""
    with pytest.raises(DocumentError, match="unknown key"):
        load_text(FULL.replace("continue_on_failure: true", "continue_on_failur: true"))


def test_an_unknown_block_is_reported_against_the_step_that_names_it(host: PluginHost) -> None:
    definition = load_text("format: dirigent/v1\ncode: missing\nsteps:\n  a: { block: nope.gone }\n")
    issues = validate_against_catalog(definition, host.catalog())
    assert [issue.location for issue in issues] == ["steps.a.block"]
    assert "no block" in issues[0].message


def test_a_step_config_is_validated_against_the_blocks_published_schema(host: PluginHost) -> None:
    definition = load_text("format: dirigent/v1\ncode: wrong\nsteps:\n  a: { block: test.echo, config: {value: 7} }\n")
    issues = validate_against_catalog(definition, host.catalog())
    assert [issue.location for issue in issues] == ["steps.a.config.value"]


def test_a_config_key_the_block_does_not_define_is_refused_against_its_published_schema(host: PluginHost) -> None:
    """Block config is opaque to the format, so the block's own schema is what closes it."""
    definition = load_text(
        "format: dirigent/v1\ncode: stray\nsteps:\n  a: { block: test.echo, config: {value: hi, uppr: true} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert [issue.location for issue in issues] == ["steps.a.config"]
    assert "uppr" in issues[0].message


def test_a_deferred_reference_is_not_type_checked_but_the_rest_still_is(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: deferred\n"
        "params: {type: object, properties: {day: {type: string}}}\n"
        "steps:\n  a: { block: test.echo, config: {value: '${params.day}'} }\n"
    )
    assert validate_against_catalog(definition, host.catalog()) == []


def test_a_block_that_runs_code_is_refused_where_the_instance_does_not_allow_it(host: PluginHost) -> None:
    """The execution path refuses it too; saying so at apply is what stops it being stored."""
    definition = load_text("format: dirigent/v1\ncode: unsafe\nsteps:\n  a: { block: test.unsafe }\n")
    assert validate_against_catalog(definition, host.catalog()) == [], "unset means the caller does not know"
    issues = validate_against_catalog(definition, host.catalog(), unsafe_allowed=[])
    assert [issue.location for issue in issues] == ["steps.a.block"]
    assert "executes code on the worker" in issues[0].message
    assert "currently allowed: none" in issues[0].message, "the list is the allowlist, not the reason"
    assert validate_against_catalog(definition, host.catalog(), unsafe_allowed=["test.unsafe"]) == []


def test_a_scheme_no_backend_claims_is_refused_and_a_request_url_is_not(host: PluginHost) -> None:
    """Only a field a block publishes as a storage URI is read as one."""
    addressed = load_text(
        "format: dirigent/v1\ncode: stored\nsteps:\n  a: { block: test.storing, config: {target: 'gs://bucket/out'} }\n"
    )
    issues = validate_against_catalog(addressed, host.catalog(), storage_schemes=["file", "s3"])
    assert [issue.location for issue in issues] == ["steps.a.config.target"]
    assert "no storage backend claims 'gs'" in issues[0].message
    assert validate_against_catalog(addressed, host.catalog()) == [], "unset means the caller does not know"

    requested = load_text(
        "format: dirigent/v1\ncode: fetched\n"
        "steps:\n  a: { block: test.storing, config: {url: 'https://example.org/x'} }\n"
    )
    assert validate_against_catalog(requested, host.catalog(), storage_schemes=["file", "s3"]) == [], (
        "the same block's url is not a storage URI, and nothing tells them apart by looking"
    )


def test_a_document_may_carry_the_connections_it_names(host: PluginHost) -> None:
    """A published example has to run somewhere that holds no connection of its own."""
    definition = load_text(
        "format: dirigent/v1\ncode: self-contained\n"
        "connections:\n  demo: {kind: http, config: {base_url: 'https://example.org'}}\n"
        "requires: {connections: [demo]}\n"
        "steps:\n  a: { block: test.echo, config: {value: hi} }\n"
    )
    assert definition.connections["demo"].kind == "http"
    assert definition.connections["demo"].config == {"base_url": "https://example.org"}
    assert validate_against_catalog(definition, host.catalog()) == [], "it satisfies its own reference"


def test_a_connection_the_document_does_not_carry_is_still_reported(host: PluginHost) -> None:
    """Carrying one name does not excuse another that nothing provides."""
    definition = load_text(
        "format: dirigent/v1\ncode: half-contained\n"
        "connections:\n  demo: {kind: http, config: {base_url: 'https://example.org'}}\n"
        "requires: {connections: [demo, warehouse]}\n"
        "steps:\n  a: { block: test.echo, config: {value: hi} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert [issue.location for issue in issues] == ["requires.connections.1"]
    assert "warehouse" in issues[0].message


def test_a_carried_connection_survives_the_canonical_round_trip(host: PluginHost) -> None:
    """It is part of the document, so an export that dropped it would not be the same document."""
    text = (
        "format: dirigent/v1\ncode: round-trip\n"
        "connections:\n  demo: {kind: http, config: {base_url: 'https://example.org'}}\n"
        "steps:\n  a: { block: test.echo, config: {value: hi} }\n"
    )
    again = load_document(canonical_document(load_text(text)))
    assert isinstance(again, PipelineDefinition)
    assert again.connections == load_text(text).connections


def test_requires_reports_everything_missing_in_one_list(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: needy\n"
        "requires: {blocks: [acme.one, acme.two], connections: [warehouse]}\n"
        "steps:\n  a: { block: test.echo, config: {value: hi} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert [issue.location for issue in issues] == [
        "requires.blocks.0",
        "requires.blocks.1",
        "requires.connections.0",
    ]


def test_required_storage_is_checked_only_when_the_schemes_are_known(host: PluginHost) -> None:
    """An unclaimed scheme is refused; unknown instance schemes refuse nothing."""
    definition = load_text(
        "format: dirigent/v1\ncode: stored\n"
        "requires: {storage: [s3]}\n"
        "steps:\n  a: { block: test.echo, config: {value: hi} }\n"
    )
    refused = validate_against_catalog(definition, host.catalog(), storage_schemes=["local"])
    assert [issue.location for issue in refused] == ["requires.storage.0"]
    assert "no storage backend claims 's3' (local)" in refused[0].message
    assert validate_against_catalog(definition, host.catalog(), storage_schemes=["s3", "local"]) == []
    assert validate_against_catalog(definition, host.catalog()) == []


def test_required_schemas_are_checked_only_when_the_held_set_is_known(host: PluginHost) -> None:
    """A schema the instance does not hold is refused; an unknown held set refuses nothing."""
    definition = load_text(
        "format: dirigent/v1\ncode: needs-a-shape\n"
        "requires: {schemas: [org-unit]}\n"
        "steps:\n  a: { block: test.echo, config: {value: hi} }\n"
    )
    refused = validate_against_catalog(definition, host.catalog(), schemas=[])
    assert [issue.location for issue in refused] == ["requires.schemas.0"]
    assert "no schema coded 'org-unit' exists" in refused[0].message
    assert validate_against_catalog(definition, host.catalog(), schemas=["org-unit"]) == []
    assert validate_against_catalog(definition, host.catalog()) == []


def test_a_document_may_carry_the_schemas_it_names(host: PluginHost) -> None:
    """A document that brings its own schema satisfies its own reference, holding none itself."""
    definition = load_text(
        "format: dirigent/v1\ncode: carries-a-shape\n"
        "schemas:\n  ou-shape: {type: object, required: [id]}\n"
        "steps:\n  a: { block: test.echo, config: {value: hi, schema: ou-shape} }\n"
    )
    assert definition.schemas["ou-shape"] == {"type": "object", "required": ["id"]}
    assert validate_against_catalog(definition, host.catalog(), schemas=[]) == [], "it satisfies its own reference"


def test_a_carried_schema_survives_the_canonical_round_trip(host: PluginHost) -> None:
    """It is part of the document, so an export that dropped it would not be the same document."""
    text = (
        "format: dirigent/v1\ncode: round-trip-shape\n"
        "schemas:\n  ou-shape: {type: object, required: [id]}\n"
        "steps:\n  a: { block: test.echo, config: {value: hi} }\n"
    )
    again = load_document(canonical_document(load_text(text)))
    assert isinstance(again, PipelineDefinition)
    assert again.schemas == load_text(text).schemas


def test_a_step_naming_a_schema_no_instance_holds_and_no_document_carries_is_refused(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: unshaped\nsteps:\n"
        "  a: { block: test.echo, config: {value: hi, schema: ou-shape} }\n"
    )
    assert [issue.location for issue in validate_against_catalog(definition, host.catalog(), schemas=[])] == [
        "steps.a.config.schema"
    ]
    assert validate_against_catalog(definition, host.catalog(), schemas=["ou-shape"]) == []


def test_a_carried_schema_that_is_not_a_schema_is_refused_at_apply(host: PluginHost) -> None:
    """A carried body is never stored on its own, so this apply check is the only thing that catches it."""
    definition = load_text(
        "format: dirigent/v1\ncode: bad-shape\n"
        "schemas:\n  ou-shape: {type: nonsense}\n"
        "steps:\n  a: { block: test.echo, config: {value: hi, schema: ou-shape} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog(), schemas=[])
    assert [issue.location for issue in issues] == ["schemas.ou-shape"]
    assert "not itself valid JSON Schema" in issues[0].message


def test_a_step_naming_a_connection_this_instance_lacks_is_refused(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: unconnected\nsteps:\n"
        "  a: { block: test.echo, config: {value: hi, connection: warehouse} }\n"
    )
    assert [issue.location for issue in validate_against_catalog(definition, host.catalog())] == [
        "steps.a.config.connection"
    ]
    assert validate_against_catalog(definition, host.catalog(), connections=["warehouse"]) == []


def test_a_reference_to_a_step_that_is_not_upstream_is_refused(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: unordered\nsteps:\n"
        "  a: { block: test.echo, config: {value: hi} }\n"
        "  b: { block: test.echo, config: {value: '${steps.a.output.value}'} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert "not a prerequisite" in issues[0].message


def test_a_reference_to_an_undeclared_parameter_is_refused(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: typo\n"
        "params: {type: object, properties: {day: {type: string}}}\n"
        "steps:\n  a: { block: test.echo, config: {value: '${params.dya}'} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert "undeclared parameter" in issues[0].message


def test_an_item_reference_outside_a_fan_out_is_refused(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: notmapped\nsteps:\n  a: { block: test.echo, config: {value: '${item}'} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert "no for_each" in issues[0].message


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("${nonsense.x}", "not one of params"),
        ("${run.nope}", "run.scratch"),
        ("${steps.a}", "malformed"),
    ],
)
def test_the_reference_language_is_checked_at_apply_time(host: PluginHost, reference: str, expected: str) -> None:
    definition = load_text(
        f"format: dirigent/v1\ncode: refs\nsteps:\n  a: {{ block: test.echo, config: {{value: '{reference}'}} }}\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert expected in issues[0].message


@pytest.mark.parametrize("reference", ["${run.window.start}", "${run.window.end}"])
def test_a_window_reference_passes_apply_time_because_the_run_may_carry_one(host: PluginHost, reference: str) -> None:
    definition = load_text(
        f"format: dirigent/v1\ncode: windowed\nsteps:\n  a: {{ block: test.echo, config: {{value: '{reference}'}} }}\n"
    )
    assert validate_against_catalog(definition, host.catalog()) == []


def test_an_escaped_reference_is_not_checked_as_a_reference_at_apply_time(host: PluginHost) -> None:
    """Nothing resolves it at run time, so nothing may refuse it at apply time either."""
    definition = load_text(
        "format: dirigent/v1\ncode: escaped\n"
        "steps:\n  a: { block: test.echo, config: {value: '$${GREETING} and $${params.nope}'} }\n"
    )
    assert validate_against_catalog(definition, host.catalog()) == []


def test_an_escaped_value_is_type_checked_as_the_literal_string_it_will_be(host: PluginHost) -> None:
    """Nothing defers it, so the block's published schema still applies to it."""
    definition = load_text(
        "format: dirigent/v1\ncode: literal\nsteps:\n  a: { block: test.echo, config: {value: '$${x}'} }\n"
    )
    assert validate_against_catalog(definition, host.catalog()) == []


def test_a_window_reference_that_names_neither_edge_is_refused_at_apply_time(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: windowed\n"
        "steps:\n  a: { block: test.echo, config: {value: '${run.window.middle}'} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert "run.window.start and run.window.end" in issues[0].message


def test_a_for_each_is_validated_the_way_a_config_is(host: PluginHost) -> None:
    """``for_each`` carries references like any other field, and is validated as one."""
    definition = load_text(
        "format: dirigent/v1\ncode: unmapped\n"
        "params: {type: object, properties: {day: {type: string}}}\n"
        "steps:\n  a: { block: test.echo, for_each: '${params.regions}', config: {value: '${item}'} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert [issue.location for issue in issues] == ["steps.a.for_each"]
    assert "undeclared parameter" in issues[0].message


def test_a_for_each_may_not_read_a_step_output(host: PluginHost) -> None:
    """Fan-out cardinality is fixed when the run is created, before any step has run."""
    definition = load_text(
        "format: dirigent/v1\ncode: too-late\nsteps:\n"
        "  a: { block: test.echo, config: {value: hi} }\n"
        "  b: { block: test.echo, depends_on: [a], for_each: '${steps.a.output.value}', config: {value: '${item}'} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert [issue.location for issue in issues] == ["steps.b.for_each"]
    assert "expanded when the run is created" in issues[0].message


def test_a_literal_string_for_each_is_refused_at_apply_time(host: PluginHost) -> None:
    """A string that interpolates nothing is still a string at run time, so it maps over nothing."""
    definition = load_text(
        "format: dirigent/v1\ncode: literal\nsteps:\n"
        "  a: { block: test.echo, for_each: '[\"a\", \"b\"]', config: {value: '${item}'} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert [issue.location for issue in issues] == ["steps.a.for_each"]
    assert "literal string, not a list" in issues[0].message


def test_a_for_each_list_written_in_the_document_is_accepted(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: written-out\nsteps:\n"
        "  a: { block: test.echo, for_each: [oslo, bergen], config: {value: '${item}'} }\n"
    )
    assert validate_against_catalog(definition, host.catalog()) == []


def test_a_for_each_that_interpolates_anywhere_is_accepted(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: interpolated\n"
        "params: {type: object, properties: {regions: {type: array}}}\n"
        "steps:\n  a: { block: test.echo, for_each: 'the ${params.regions}', config: {value: '${item}'} }\n"
    )
    assert validate_against_catalog(definition, host.catalog()) == []


def test_a_declared_parameter_in_a_for_each_is_accepted(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: mapped\n"
        "params: {type: object, properties: {regions: {type: array}}}\n"
        "steps:\n  a: { block: test.echo, for_each: '${params.regions}', config: {value: '${item}'} }\n"
    )
    assert validate_against_catalog(definition, host.catalog()) == []


BAD_PROGRAM = (
    "format: dirigent/v1\ncode: recase\nsteps:\n"
    "  a: { block: transform.upper, config: {input: ada, program: sideways} }\n"
)


def test_a_block_refuses_its_own_config_at_apply_when_the_live_block_is_available(host: PluginHost) -> None:
    """The schema says the program is a string; only the block can say it is not a program."""
    definition = load_text(BAD_PROGRAM)
    issues = validate_against_catalog(definition, host.catalog(), blocks=host.blocks)
    assert [issue.location for issue in issues] == ["steps.a.config"]
    assert "'sideways' is not a case" in issues[0].message


@pytest.mark.parametrize(
    "config",
    ["{program: upper}", "{program: upper, input: ada, input_uri: 'file://in.json'}"],
    ids=["neither", "both"],
)
def test_a_transform_naming_no_input_or_two_is_refused_by_the_published_schema(config: str, host: PluginHost) -> None:
    """The rule is a model validator, and the schema carries it so apply is where it lands."""
    definition = load_text(
        f"format: dirigent/v1\ncode: recase\nsteps:\n  a: {{ block: transform.upper, config: {config} }}\n"
    )
    assert [issue.location for issue in validate_against_catalog(definition, host.catalog())] == ["steps.a.config"]


def test_a_caller_holding_no_blocks_checks_the_schema_alone(host: PluginHost) -> None:
    assert validate_against_catalog(load_text(BAD_PROGRAM), host.catalog()) == []


def test_a_config_the_schema_refuses_is_reported_once_and_the_block_is_not_asked_as_well(
    host: PluginHost,
) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: recase\nsteps:\n  a: { block: transform.upper, config: {input: ada, program: 7} }\n"
    )
    issues = validate_against_catalog(definition, host.catalog(), blocks=host.blocks)
    assert [issue.location for issue in issues] == ["steps.a.config.program"]


def test_a_program_that_is_still_a_reference_is_left_to_the_run(host: PluginHost) -> None:
    """A block asked to compile a ``${...}`` would refuse the reference rather than the program."""
    definition = load_text(
        "format: dirigent/v1\ncode: recase\n"
        "params: {type: object, properties: {case: {type: string}}}\n"
        "steps:\n  a: { block: transform.upper, config: {input: ada, program: '${params.case}'} }\n"
    )
    assert validate_against_catalog(definition, host.catalog(), blocks=host.blocks) == []


BAD_JQ_PROGRAM = (
    "format: dirigent/v1\ncode: reshape\nsteps:\n"
    "  a: { block: transform.jq, config: {input: [], program: '[.[] | '} }\n"
)


def test_the_jq_engine_that_ships_refuses_its_own_program_at_apply() -> None:
    """The same hook against the real catalog and the real blocks, not the test engines."""
    installed = load_plugin_host()
    issues = validate_against_catalog(load_text(BAD_JQ_PROGRAM), installed.catalog(), blocks=installed.blocks)
    assert [issue.location for issue in issues] == ["steps.a.config"]
    assert "syntax error, unexpected end of file" in issues[0].message


BAD_CONVERT_PAIR = (
    "format: dirigent/v1\ncode: recode\nsteps:\n"
    "  a: { block: convert.std, config: {input: 'a,b', from: csv, to: csv} }\n"
)


def test_the_std_codec_that_ships_refuses_a_pair_it_has_no_codec_for_at_apply() -> None:
    """A codec engine's apply-time check is the same hook, refusing a pair rather than a program."""
    installed = load_plugin_host()
    issues = validate_against_catalog(load_text(BAD_CONVERT_PAIR), installed.catalog(), blocks=installed.blocks)
    assert [issue.location for issue in issues] == ["steps.a.config"]
    assert "convert.std does not convert csv to csv" in issues[0].message
    assert "json to csv" in issues[0].message


BAD_ELEMENT_PROGRAMS = (
    "format: dirigent/v1\ncode: winnow\nsteps:\n"
    "  a: { block: map.jq, config: {input: [], program: '{station, '} }\n"
    "  b: { block: filter.jq, config: {input: [], program: 'select('} }\n"
)


def test_the_element_wise_engines_refuse_their_own_programs_at_apply() -> None:
    """A map and a filter compile the same way a transform does, so a bad program never reaches a run."""
    installed = load_plugin_host()
    issues = validate_against_catalog(load_text(BAD_ELEMENT_PROGRAMS), installed.catalog(), blocks=installed.blocks)
    assert [issue.location for issue in issues] == ["steps.a.config", "steps.b.config"]
    assert all("syntax error" in issue.message for issue in issues)


def test_a_block_with_nothing_extra_to_say_adds_no_issues(host: PluginHost) -> None:
    definition = load_text("format: dirigent/v1\ncode: fine\nsteps:\n  a: { block: test.echo }\n")
    assert validate_against_catalog(definition, host.catalog(), blocks=host.blocks) == []


def test_offline_validation_skips_what_needs_an_instance(host: PluginHost) -> None:
    definition = load_text("format: dirigent/v1\ncode: offline\nsteps:\n  a: { block: nobody.knows }\n")
    assert validate_against_catalog(definition, host.catalog(), check_blocks=False) == []


def test_a_summary_is_what_a_plan_and_a_listing_show() -> None:
    summary = summarize(load_text(FULL))
    assert summary.code == "daily-load"
    assert summary.steps == ["cleanup", "push", "wait"]
    assert summary.blocks == ["test.echo", "test.tick"]
    assert summary.digest.startswith("sha256:")


def test_a_bad_cron_expression_is_reported_by_the_plan_not_after_the_version_is_written(
    host: PluginHost,
) -> None:
    """A dry run that says "fine" and a real apply that then refuses is the worst pairing."""
    definition = load_text(
        "format: dirigent/v1\ncode: badclock\nsteps:\n  a: { block: test.echo }\n"
        "triggers:\n  schedules:\n    - code: nightly\n      cron: 'not a cron'\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert [issue.location for issue in issues] == ["triggers.schedules[0].nightly"]
    assert "is not a cron expression" in issues[0].message


def test_a_timezone_this_host_does_not_know_is_reported_by_the_plan(host: PluginHost) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: badzone\nsteps:\n  a: { block: test.echo }\n"
        "triggers:\n  schedules:\n    - code: nightly\n      cron: '0 5 * * *'\n      timezone: Mars/Olympus\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert "is not an IANA timezone" in issues[0].message


def test_a_schedule_pinning_a_parameter_the_schema_refuses_is_reported_by_the_plan(host: PluginHost) -> None:
    """A pin is the whole parameter object of every firing, so a bad one is a bad document."""
    header = (
        "format: dirigent/v1\ncode: badpin\n"
        "params: {type: object, properties: {day: {type: string}}, required: [day]}\n"
        "steps:\n  a: { block: test.echo }\n"
        "triggers:\n  schedules:\n    - code: nightly\n      cron: '0 5 * * *'\n"
    )
    mistyped = validate_against_catalog(load_text(header + "      params: {day: 3}\n"), host.catalog())
    assert [issue.location for issue in mistyped] == ["triggers.schedules[0].params"]
    assert "parameter day is invalid" in mistyped[0].message

    unpinned = validate_against_catalog(load_text(header), host.catalog())
    assert [issue.location for issue in unpinned] == ["triggers.schedules[0].params"]
    assert "'day' is a required property" in unpinned[0].message

    assert validate_against_catalog(load_text(header + "      params: {day: '2026-01-01'}\n"), host.catalog()) == []


def test_a_webhook_mapping_no_delivery_could_satisfy_is_reported_by_the_plan(host: PluginHost) -> None:
    """A mapping is only checkable at declaration; the first delivery is far too late to learn."""
    header = (
        "format: dirigent/v1\ncode: badmap\n"
        "params: {type: object, properties: {day: {type: string}}, required: [day]}\n"
        "steps:\n  a: { block: test.echo }\n"
        "triggers:\n  webhooks:\n    - code: inbound\n"
    )
    unparseable = validate_against_catalog(
        load_text(header + "      params_from_payload: {day: '$.run..date'}\n"), host.catalog()
    )
    assert [issue.location for issue in unparseable] == ["triggers.webhooks[0].params_from_payload"]
    assert unparseable[0].message == "'$.run..date' is not a payload path: an empty segment"

    undeclared = validate_against_catalog(
        load_text(header + "      params_from_payload: {day: '$.run.date', extra: '$.run.extra'}\n"), host.catalog()
    )
    assert [issue.location for issue in undeclared] == ["triggers.webhooks[0].params_from_payload"]
    assert undeclared[0].message == "'extra' is not a parameter this pipeline declares (day)"

    unmapped = validate_against_catalog(load_text(header), host.catalog())
    assert [issue.location for issue in unmapped] == ["triggers.webhooks[0].params_from_payload"]
    assert "the required parameter 'day' is not mapped" in unmapped[0].message

    assert (
        validate_against_catalog(load_text(header + "      params_from_payload: {day: '$.run.date'}\n"), host.catalog())
        == []
    )


def test_a_parameter_schema_that_is_not_one_is_reported_once_rather_than_once_per_trigger(
    host: PluginHost,
) -> None:
    definition = load_text(
        "format: dirigent/v1\ncode: mistyped\nparams: {type: objcet}\nsteps:\n  a: { block: test.echo }\n"
        "triggers:\n  schedules:\n    - code: nightly\n      cron: '0 5 * * *'\n"
        "    - code: hourly\n      interval: 1h\n"
        "  webhooks:\n    - code: inbound\n      params_from_payload: {day: '$.run.date'}\n"
    )
    assert [issue.location for issue in validate_against_catalog(definition, host.catalog())] == ["params"]


def test_a_one_time_schedule_written_without_an_offset_is_read_in_its_own_zone() -> None:
    """``at: 2026-09-01T05:00:00`` is what a person writes, and it has no offset."""
    definition = load_text(
        "format: dirigent/v1\ncode: onetime\nsteps:\n  a: { block: test.echo }\n"
        "triggers:\n  schedules:\n    - code: once\n      at: 2026-09-01T05:00:00\n"
        "      timezone: Europe/Oslo\n"
    )
    scheduled = definition.triggers.schedules[0]
    assert scheduled.at is not None
    assert scheduled.at.tzinfo is not None
    assert scheduled.at.utcoffset() == timedelta(hours=2)


def test_a_parameter_schema_that_is_not_a_schema_is_refused_at_apply(host: PluginHost) -> None:
    """Nothing else checks it, and the first run would otherwise fail from inside jsonschema."""
    definition = load_text(
        "format: dirigent/v1\ncode: mistyped\nparams: {type: objcet}\nsteps:\n  a: { block: test.echo }\n"
    )
    issues = validate_against_catalog(definition, host.catalog())
    assert [issue.location for issue in issues] == ["params"]
    assert "not itself valid JSON Schema at type" in issues[0].message
    assert "'objcet' is not valid under any of the given schemas" in issues[0].message
    offline = validate_against_catalog(definition, host.catalog(), check_blocks=False)
    assert [issue.location for issue in offline] == ["params"], "the offline path has no catalog and checks it anyway"


def test_a_parameter_schema_that_is_one_and_a_document_without_any_are_both_accepted(host: PluginHost) -> None:
    absent = load_text("format: dirigent/v1\ncode: plain\nsteps:\n  a: { block: test.echo }\n")
    assert validate_against_catalog(absent, host.catalog()) == []
    declared = load_text(
        "format: dirigent/v1\ncode: declared\n"
        "params: {type: object, properties: {day: {type: string}}, required: [day]}\n"
        "steps:\n  a: { block: test.echo }\n"
    )
    assert validate_against_catalog(declared, host.catalog()) == []


def test_a_report_section_survives_the_canonical_form_even_when_it_says_nothing() -> None:
    """``report: {}`` is what asks for the built-in template, so it cannot be dropped as empty."""
    document = canonical_document(load_text(MINIMAL + "report: {}\n"))
    assert document["report"] == {}


def test_a_document_with_no_report_says_nothing_about_one() -> None:
    assert "report" not in canonical_document(load_text(MINIMAL))


def test_a_report_template_round_trips_through_the_canonical_form() -> None:
    document = load_text(MINIMAL + 'report:\n  template: "# {{ run.status }}"\n')
    assert load_document(canonical_document(document)) == document
