"""Tests for the pipeline definition model: the graph checks and parameter validation."""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from dirigent_common import base_format_checker, format_checker_with
from dirigent_core.engine.definition import (
    ConcurrencyPolicy,
    ItemPolicy,
    ParameterError,
    PipelineDefinition,
    RetryPolicy,
    StepDefinition,
    TimeoutAction,
    TriggerRule,
    dump_definition,
    load_definition,
)


def chain() -> PipelineDefinition:
    """A three-step chain, which most graph assertions are made against."""
    return PipelineDefinition(
        code="chain",
        steps={
            "first": StepDefinition(block="test.echo"),
            "second": StepDefinition(block="test.echo", depends_on=["first"]),
            "third": StepDefinition(block="test.echo", depends_on=["second"]),
        },
    )


def test_a_definition_round_trips_through_its_document() -> None:
    definition = chain()
    assert load_definition(dump_definition(definition)) == definition


def test_defaults_are_the_engine_semantics_the_design_names() -> None:
    step = StepDefinition(block="test.echo")
    assert step.rule is TriggerRule.ALL_SUCCESS
    assert step.items is ItemPolicy.FAIL_FAST
    assert step.on_timeout is TimeoutAction.FAIL
    assert step.continue_on_failure is False
    assert step.is_fan_out is False
    assert step.retry == RetryPolicy(max_attempts=1, backoff=timedelta(seconds=30))
    assert chain().concurrency is ConcurrencyPolicy.ALLOW


def test_roots_and_dependents_describe_the_graph() -> None:
    definition = chain()
    assert definition.roots == ["first"]
    assert definition.dependents_of("first") == ["second"]
    assert definition.descendants_of("first") == ["second", "third"]
    assert definition.descendants_of("third") == []
    assert definition.topological_order() == ["first", "second", "third"]


def test_a_diamond_orders_prerequisites_before_dependents() -> None:
    definition = PipelineDefinition(
        code="diamond",
        steps={
            "root": StepDefinition(block="test.echo"),
            "left": StepDefinition(block="test.echo", depends_on=["root"]),
            "right": StepDefinition(block="test.echo", depends_on=["root"]),
            "join": StepDefinition(block="test.echo", depends_on=["left", "right"]),
        },
    )
    order = definition.topological_order()
    assert order[0] == "root"
    assert order[-1] == "join"
    assert set(definition.descendants_of("root")) == {"left", "right", "join"}


def test_an_unknown_prerequisite_is_refused() -> None:
    with pytest.raises(ValidationError, match="depends on unknown step 'ghost'"):
        PipelineDefinition(code="broken", steps={"a": StepDefinition(block="test.echo", depends_on=["ghost"])})


def test_a_self_edge_is_refused() -> None:
    with pytest.raises(ValidationError, match="depends on itself"):
        PipelineDefinition(code="broken", steps={"a": StepDefinition(block="test.echo", depends_on=["a"])})


def test_a_cycle_is_refused_and_names_the_steps() -> None:
    with pytest.raises(ValidationError, match=r"\['a', 'b'\] form a cycle"):
        PipelineDefinition(
            code="broken",
            steps={
                "a": StepDefinition(block="test.echo", depends_on=["b"]),
                "b": StepDefinition(block="test.echo", depends_on=["a"]),
            },
        )


def test_a_pipeline_needs_at_least_one_step() -> None:
    with pytest.raises(ValidationError):
        PipelineDefinition(code="empty", steps={})


def test_a_block_id_must_be_a_namespaced_dotted_path() -> None:
    with pytest.raises(ValidationError):
        StepDefinition(block="NotABlock")


def test_a_step_name_must_be_snake_case() -> None:
    with pytest.raises(ValidationError, match="a-z0-9_"):
        PipelineDefinition(code="bad", steps={"has space": StepDefinition(block="test.echo")})
    with pytest.raises(ValidationError, match="a-z0-9_"):
        PipelineDefinition(code="bad", steps={"kebab-case": StepDefinition(block="test.echo")})


def test_a_pipeline_name_must_be_a_dns_label() -> None:
    with pytest.raises(ValidationError):
        PipelineDefinition(code="Not A Name", steps={"a": StepDefinition(block="test.echo")})
    with pytest.raises(ValidationError):
        PipelineDefinition(code="snake_case", steps={"a": StepDefinition(block="test.echo")})


def test_parameters_are_validated_against_the_published_schema() -> None:
    definition = PipelineDefinition(
        code="parameterised",
        params={
            "type": "object",
            "required": ["day"],
            "properties": {"day": {"type": "string"}, "limit": {"type": "integer", "default": 10}},
        },
        steps={"a": StepDefinition(block="test.echo")},
    )
    assert definition.validate_params({"day": "2026-08-28"}, base_format_checker()) == {
        "day": "2026-08-28",
        "limit": 10,
    }
    assert definition.validate_params({"day": "x", "limit": 2}, base_format_checker())["limit"] == 2
    with pytest.raises(ParameterError, match="'day' is a required property"):
        definition.validate_params({}, base_format_checker())
    with pytest.raises(ParameterError, match="parameter limit is invalid"):
        definition.validate_params({"day": "x", "limit": "many"}, base_format_checker())


def test_a_parameter_schema_that_is_not_a_schema_refuses_the_run_rather_than_escaping() -> None:
    """A version stored before apply checked the schema still has to fail as a ParameterError."""
    definition = PipelineDefinition(
        code="mistyped",
        params={"type": "objcet"},
        steps={"a": StepDefinition(block="test.echo")},
    )
    with pytest.raises(ParameterError, match="parameter schema is not itself valid JSON Schema"):
        definition.validate_params({"day": "x"}, base_format_checker())

    dangling = PipelineDefinition(
        code="dangling",
        params={"type": "object", "properties": {"day": {"$ref": "#/$defs/nope"}}},
        steps={"a": StepDefinition(block="test.echo")},
    )
    with pytest.raises(ParameterError, match="parameter schema is not itself valid JSON Schema"):
        dangling.validate_params({"day": "x"}, base_format_checker())


def test_a_parameter_format_asserts_with_the_instances_checker() -> None:
    """A ``format`` on a parameter is checked, exactly as it is at a validate.schema gate."""
    definition = PipelineDefinition(
        code="dated",
        params={"type": "object", "properties": {"day": {"type": "string", "format": "date"}}},
        steps={"a": StepDefinition(block="test.echo")},
    )
    assert definition.validate_params({"day": "2026-01-31"}, base_format_checker()) == {"day": "2026-01-31"}
    with pytest.raises(ParameterError, match="parameter day is invalid: .*is not a 'date'"):
        definition.validate_params({"day": "2026-13-40"}, base_format_checker())


def test_a_contributed_parameter_format_asserts_only_where_the_pack_is_installed() -> None:
    definition = PipelineDefinition(
        code="uided",
        params={"type": "object", "properties": {"ou": {"type": "string", "format": "even-digits"}}},
        steps={"a": StepDefinition(block="test.echo")},
    )
    with_pack = format_checker_with({"even-digits": lambda value: isinstance(value, str) and len(value) % 2 == 0})
    assert definition.validate_params({"ou": "12"}, with_pack) == {"ou": "12"}
    with pytest.raises(ParameterError, match="even-digits"):
        definition.validate_params({"ou": "123"}, with_pack)
    assert definition.validate_params({"ou": "123"}, base_format_checker()) == {"ou": "123"}


def test_a_pipeline_with_no_parameter_schema_accepts_nothing_extra() -> None:
    definition = PipelineDefinition(code="plain", steps={"a": StepDefinition(block="test.echo")})
    assert definition.validate_params({}, base_format_checker()) == {}


def test_a_retry_policy_is_bounded() -> None:
    with pytest.raises(ValidationError):
        RetryPolicy(max_attempts=0)
    with pytest.raises(ValidationError):
        RetryPolicy(jitter=2.0)
    with pytest.raises(ValidationError):
        RetryPolicy(multiplier=0.5)


def test_a_fan_out_step_declares_itself() -> None:
    assert StepDefinition(block="test.echo", for_each="${params.regions}").is_fan_out
    assert StepDefinition(block="test.echo", for_each=["a", "b"]).is_fan_out


def tagged(tags: list[str]) -> PipelineDefinition:
    """A one-step pipeline wearing whatever tags a case hands over."""
    return PipelineDefinition(code="labelled", tags=tags, steps={"a": StepDefinition(block="test.echo")})


def test_a_document_wears_no_tags_until_it_declares_some() -> None:
    assert PipelineDefinition(code="plain", steps={"a": StepDefinition(block="test.echo")}).tags == []


@pytest.mark.parametrize(
    "tag",
    ["-leading", "has space", "under_score", "a" * 33, "", "dot.ted", "Has Space"],
    ids=["leading-hyphen", "space", "underscore", "too-long", "empty", "dotted", "shouted-space"],
)
def test_a_tag_that_is_not_a_tag_is_refused_and_the_index_is_named(tag: str) -> None:
    with pytest.raises(ValidationError, match=r"tags\[1\]"):
        tagged(["climate", tag])


def test_the_refusal_names_the_tag_as_it_was_written_and_states_the_rule() -> None:
    with pytest.raises(ValidationError, match=r"tags\[0\] 'Nightly Import' is not a valid tag: a tag is lowercased"):
        tagged(["Nightly Import"])


def test_a_tag_may_carry_digits_and_inner_hyphens() -> None:
    assert tagged(["s3", "weekly-import", "v2-beta", "2024-archive"]).tags == [
        "s3",
        "weekly-import",
        "v2-beta",
        "2024-archive",
    ]


def test_a_tag_is_lowercased_at_validation_so_every_comparison_after_it_is_exact() -> None:
    assert tagged(["S3", "Weekly-Import"]).tags == ["s3", "weekly-import"]


def test_two_spellings_of_one_tag_are_the_same_tag_declared_twice() -> None:
    with pytest.raises(ValidationError, match=r"tags\[1\] 'climate' is declared twice"):
        tagged(["climate", "CLIMATE"])


def test_a_tag_declared_twice_is_refused_at_the_repetition() -> None:
    with pytest.raises(ValidationError, match=r"tags\[2\] 'climate' is declared twice"):
        tagged(["climate", "http", "climate"])


def test_a_document_may_wear_sixteen_tags_and_no_more() -> None:
    assert len(tagged([f"tag-{index}" for index in range(16)]).tags) == 16
    with pytest.raises(ValidationError, match="at most 16 tags, and this one declares 17"):
        tagged([f"tag-{index}" for index in range(17)])


def test_the_canonical_form_leaves_an_untagged_document_saying_nothing_about_tags() -> None:
    """An empty list is the default, so tagging nothing changes no digest that already exists."""
    plain = PipelineDefinition(code="plain", steps={"a": StepDefinition(block="test.echo")})
    assert "tags" not in dump_definition(plain)
    assert dump_definition(tagged(["climate"]))["tags"] == ["climate"]


def test_tags_survive_a_round_trip_in_the_order_they_were_written() -> None:
    """A tag list is a list, not a set: the order an author chose is the order it reads back."""
    assert load_definition(dump_definition(tagged(["http", "climate"]))).tags == ["http", "climate"]
