"""Tests for the jq engines: the transform, map and filter a pipeline used to shell out to jq for."""

import json

import pytest

from dirigent_blocks.transform_jq import JqFilterer, JqMapper, JqProgramConfig, JqTransformer
from dirigent_common import JQ_MEDIA_TYPE
from dirigent_plugin import BlockFailure, ErrorClass, Filterer, Mapper, Transformer
from dirigent_testing import FakeContext, FakeStorage, call_block

READINGS = [
    {"id": "r1", "status": "active", "meta": {"region": "east"}},
    {"id": "r2", "status": "retired", "meta": {"region": "west"}},
    {"id": "r3", "status": "active", "meta": {"region": "north"}},
]

SELECT_ACTIVE = '[.[] | select(.status == "active") | {id, region: .meta.region}]'

RESHAPED = [{"id": "r1", "region": "east"}, {"id": "r3", "region": "north"}]

CELSIUS = [{"station": "st-1", "c": 4}, {"station": "st-2", "c": -3}]

TO_FAHRENHEIT = "{station, fahrenheit: (.c * 9 / 5 + 32 | round)}"


def test_the_engine_is_transform_jq_and_needs_no_allowlist_entry() -> None:
    assert JqTransformer.spec.id == "transform.jq"
    assert JqTransformer.spec.local_execution is False


async def test_a_program_selects_and_reshapes_an_inline_value(ctx: FakeContext) -> None:
    output = await call_block(JqTransformer(), {"input": READINGS, "program": SELECT_ACTIVE}, ctx)

    assert output.model_dump() == {"value": RESHAPED, "output_uri": None, "output_bytes": None}


async def test_the_same_reshape_reads_its_input_from_storage(ctx: FakeContext, storage: FakeStorage) -> None:
    storage.path_for("file://readings.json").write_bytes(json.dumps(READINGS).encode())

    output = await call_block(JqTransformer(), {"input_uri": "file://readings.json", "program": SELECT_ACTIVE}, ctx)

    assert output.model_dump()["value"] == RESHAPED


async def test_save_to_streams_the_result_and_the_output_names_where_it_went(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    output = await call_block(
        JqTransformer(),
        {"input": READINGS, "program": SELECT_ACTIVE, "save_to": "file://out/reshaped.json"},
        ctx,
    )

    written = storage.path_for("file://out/reshaped.json").read_bytes()
    assert json.loads(written) == RESHAPED
    assert output.model_dump() == {
        "value": None,
        "output_uri": "file://out/reshaped.json",
        "output_bytes": len(written),
    }


async def test_a_program_with_several_outputs_produces_the_list_of_them(ctx: FakeContext) -> None:
    output = await call_block(JqTransformer(), {"input": [{"id": "r1"}, {"id": "r2"}], "program": ".[]"}, ctx)

    assert output.model_dump()["value"] == [{"id": "r1"}, {"id": "r2"}]


async def test_a_program_producing_nothing_is_refused_rather_than_passing_a_null_on(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(JqTransformer(), {"input": READINGS, "program": "empty"}, ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "emits [] or null explicitly" in raised.value.message


def test_a_bad_program_is_refused_at_apply_with_jqs_own_message() -> None:
    config = JqTransformer.config_model.model_validate({"input": READINGS, "program": "[.[] | "})

    issues = JqTransformer().check_config(config)

    assert len(issues) == 1
    assert "syntax error, unexpected end of file" in issues[0]


def test_a_program_that_compiles_is_passed_without_comment() -> None:
    config = JqTransformer.config_model.model_validate({"input": READINGS, "program": SELECT_ACTIVE})

    assert JqTransformer().check_config(config) == []


async def test_a_program_that_compiles_but_meets_the_wrong_data_is_rejected(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(JqTransformer(), {"input": ["ada"], "program": ".[] | .name"}, ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "Cannot index string with string" in raised.value.message


async def test_the_worker_environment_is_not_readable_through_a_program(ctx: FakeContext) -> None:
    """Env and $ENV are where an instance's own secrets live, so a program sees neither."""
    output = await call_block(
        JqTransformer(), {"input": READINGS, "program": "{env: env, dollar: $ENV, key: env.PATH}"}, ctx
    )

    assert output.model_dump()["value"] == {"env": {}, "dollar": {}, "key": None}


def test_the_map_and_filter_engines_ship_beside_the_transform_one_and_need_no_allowlist_entry() -> None:
    assert JqMapper.spec.id == "map.jq"
    assert JqFilterer.spec.id == "filter.jq"
    assert JqMapper.spec.local_execution is False
    assert JqFilterer.spec.local_execution is False


async def test_a_map_program_replaces_every_element_with_its_one_output(ctx: FakeContext) -> None:
    output = await call_block(JqMapper(), {"input": CELSIUS, "program": TO_FAHRENHEIT}, ctx)

    assert output.model_dump()["value"] == [
        {"station": "st-1", "fahrenheit": 39},
        {"station": "st-2", "fahrenheit": 27},
    ]


async def test_a_map_program_meeting_the_wrong_element_is_rejected_naming_the_element(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(JqMapper(), {"input": [{"c": 4}, "st-2"], "program": TO_FAHRENHEIT}, ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message.startswith("element 1: ")
    assert "Cannot index string with" in raised.value.message


@pytest.mark.parametrize(
    ("program", "produced"),
    [("empty", "0 outputs"), (".c, .station", "2 outputs")],
    ids=["none", "several"],
)
async def test_a_map_program_that_does_not_produce_exactly_one_output_per_element_is_steered_to_another_verb(
    program: str, produced: str, ctx: FakeContext
) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(JqMapper(), {"input": CELSIUS, "program": program}, ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert f"element 0: the program produced {produced}" in raised.value.message
    assert "a filter.jq step" in raised.value.message
    assert "a transform.jq step" in raised.value.message


async def test_a_filter_program_keeps_the_elements_it_answers_true_for(ctx: FakeContext) -> None:
    output = await call_block(JqFilterer(), {"input": READINGS, "program": '.status == "active"'}, ctx)

    assert output.model_dump()["value"] == [READINGS[0], READINGS[2]]


async def test_a_filter_program_answering_something_that_is_not_a_verdict_is_refused_naming_both(
    ctx: FakeContext,
) -> None:
    """Jq's truthiness is not applied, so a program yielding 0 is a mistake rather than a dropped element."""
    with pytest.raises(BlockFailure) as raised:
        await call_block(JqFilterer(), {"input": CELSIUS, "program": ".c"}, ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "element 0: the program answered 4" in raised.value.message
    assert "'.count > 0'" in raised.value.message


async def test_a_filter_program_that_does_not_answer_once_per_element_is_steered_to_another_verb(
    ctx: FakeContext,
) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(JqFilterer(), {"input": CELSIUS, "program": "empty"}, ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "element 0: the program produced 0 outputs" in raised.value.message
    assert "map.jq or transform.jq step" in raised.value.message


def test_a_bad_map_or_filter_program_is_refused_at_apply_with_jqs_own_message() -> None:
    config = JqMapper.config_model.model_validate({"input": CELSIUS, "program": "{station, "})

    assert len(JqMapper().check_config(config)) == 1
    assert "syntax error" in JqMapper().check_config(config)[0]
    assert "syntax error" in JqFilterer().check_config(config)[0]


async def test_the_worker_environment_is_not_readable_through_a_map_program(ctx: FakeContext) -> None:
    """The sandbox is the engines', not the verb's: a map program sees the same empty object."""
    output = await call_block(JqMapper(), {"input": [1], "program": "{env: env, dollar: $ENV, key: env.PATH}"}, ctx)

    assert output.model_dump()["value"] == [{"env": {}, "dollar": {}, "key": None}]


async def test_the_worker_environment_is_not_readable_through_a_filter_program(ctx: FakeContext) -> None:
    """The same shadowing, answered as a verdict: a program asking the environment learns nothing."""
    output = await call_block(JqFilterer(), {"input": [1, 2], "program": "env.PATH != null or $ENV != {}"}, ctx)

    assert output.model_dump()["value"] == []


@pytest.mark.parametrize("engine", [JqTransformer, JqMapper, JqFilterer])
def test_every_verb_publishes_its_program_as_jq(engine: type[Transformer] | type[Mapper] | type[Filterer]) -> None:
    """A form generated from the schema needs the language named to edit the field as source."""
    published = engine.config_model.model_json_schema()["properties"]["program"]

    assert published["contentMediaType"] == JQ_MEDIA_TYPE


def test_a_program_keeps_the_lines_it_was_written_on() -> None:
    """A jq program is written over several lines, and the config carries it exactly as typed."""
    written = "group_by(.region)\n| map({region: .[0].region, total: (map(.count) | add)})\n"
    config = JqProgramConfig.model_validate({"input": [], "program": written})

    assert config.program == written
