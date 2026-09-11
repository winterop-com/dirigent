"""Tests for the transform verb frames, driven by toy engines that stand in for real ones."""

from typing import cast

import pytest
from pydantic import JsonValue, ValidationError

from dirigent_plugin import (
    BlockFailure,
    Converter,
    ErrorClass,
    Filterer,
    Mapper,
    Transformer,
    TransformError,
)
from dirigent_testing import FakeContext, FakeStorage, call_block

PROGRAMS = ("upper", "lower")

#: The one pair NoopConverter supports, source and target included.
PAIR = {"source": "file://in.csv", "target": "file://out.csv", "from": "a", "to": "b"}


class CaseTransformer(Transformer):
    """A program engine whose whole language is the two words in PROGRAMS."""

    kind = "upper"
    summary = "Change the case of every string in a value."

    def compile(self, program: str) -> object:
        """Accept one of the two words this engine knows, and nothing else."""
        if program not in PROGRAMS:
            raise TransformError(f"{program!r} is not a case: write one of {', '.join(PROGRAMS)}")
        return program

    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Recase every string, walking a list so a stored array works too."""
        if isinstance(value, str):
            return value.upper() if compiled == "upper" else value.lower()
        if isinstance(value, list):
            return [self.apply(compiled, item) for item in value]
        return value


class NoopConverter(Converter):
    """A codec engine that supports one pair and copies the bytes."""

    kind = "noop"
    summary = "Copy bytes from one format name to another."
    pairs = frozenset({("a", "b")})

    def convert(self, source: bytes, *, source_format: str, target_format: str) -> bytes:
        """Hand back exactly what arrived."""
        return source


class UpperMapper(Mapper):
    """A map engine whose whole language is the word in PROGRAM, applied to one element."""

    kind = "upper"
    summary = "Upper-case every element of a list of strings."

    def compile(self, program: str) -> object:
        """Accept the one word this engine knows, and nothing else."""
        if program != "upper":
            raise TransformError(f"{program!r} is not a case: write upper")
        return program

    def apply(self, compiled: object, value: JsonValue) -> JsonValue:
        """Upper-case one string, refusing an element that is not one."""
        if not isinstance(value, str):
            raise TransformError("this engine upper-cases strings")
        return value.upper()


class SwallowingMapper(UpperMapper):
    """A broken map engine: it replaces the frame's loop with one that drops an element."""

    kind = "swallow"
    summary = "Drop the first element instead of mapping it."

    def _map_each(self, compiled: object, elements: list[JsonValue]) -> list[JsonValue]:
        """Skip the first element, which is what the frame's length assertion is there to catch."""
        return [self.apply(compiled, element) for element in elements[1:]]


class ActiveFilterer(Filterer):
    """A filter engine whose program names the status an element has to carry to be kept."""

    kind = "status"
    summary = "Keep the elements whose status is the one the program names."

    def compile(self, program: str) -> object:
        """Accept a non-blank status name as the program."""
        if not program.strip():
            raise TransformError("write the status to keep")
        return program

    def keep(self, compiled: object, value: JsonValue) -> bool:
        """Compare the status on a reshaped copy of the element, which the frame never sees."""
        if not isinstance(value, dict):
            raise TransformError("this engine filters objects")
        seen = dict(value) | {"seen_by": "the engine"}
        return seen.get("status") == compiled


class ShoutingFilterer(ActiveFilterer):
    """A broken filter engine: it answers with a string rather than a boolean."""

    kind = "shout"
    summary = "Answer with something that is not a verdict."

    def keep(self, compiled: object, value: JsonValue) -> bool:
        """Answer 'yes', which is not an answer a filter's contract has a meaning for."""
        return cast("bool", "yes")


def test_the_frame_derives_the_block_id_and_spec_from_the_engines_kind() -> None:
    assert CaseTransformer.spec.id == "transform.upper"
    assert CaseTransformer.spec.idempotent is True
    assert CaseTransformer.spec.local_execution is False
    assert NoopConverter.spec.id == "convert.noop"
    assert UpperMapper.spec.id == "map.upper"
    assert ActiveFilterer.spec.id == "filter.status"


async def test_an_inline_value_is_transformed_and_inlined(block_ctx: FakeContext) -> None:
    output = await call_block(CaseTransformer(), {"input": ["ada", "grace"], "program": "upper"}, block_ctx)

    assert output.model_dump() == {"value": ["ADA", "GRACE"]}


async def test_a_transform_naming_no_input_is_refused(block_ctx: FakeContext) -> None:
    """A transform works on a value, so the one it is given is required rather than defaulted."""
    with pytest.raises(ValidationError, match="input"):
        await call_block(CaseTransformer(), {"program": "upper"}, block_ctx)


async def test_a_bad_program_fails_the_step_as_rejected_when_it_reaches_a_run(block_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(CaseTransformer(), {"input": "ada", "program": "sideways"}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "'sideways' is not a case" in raised.value.message


def test_check_config_returns_the_compile_error_for_a_bad_program() -> None:
    config = CaseTransformer.config_model.model_validate({"input": "ada", "program": "sideways"})

    assert CaseTransformer().check_config(config) == ["'sideways' is not a case: write one of upper, lower"]


def test_check_config_is_silent_about_a_program_that_compiles() -> None:
    config = CaseTransformer.config_model.model_validate({"input": "ada", "program": "upper"})

    assert CaseTransformer().check_config(config) == []
    assert UpperMapper().check_config(config) == []
    assert ActiveFilterer().check_config(config) == []


def test_check_config_says_nothing_about_a_config_of_another_shape() -> None:
    program = CaseTransformer.config_model.model_validate({"input": "ada", "program": "sideways"})
    pair = NoopConverter.config_model.model_validate(PAIR | {"to": "z"})

    assert CaseTransformer().check_config(pair) == []
    assert NoopConverter().check_config(program) == []
    assert UpperMapper().check_config(pair) == []
    assert ActiveFilterer().check_config(pair) == []


async def test_a_conversion_reads_the_source_object_and_writes_the_target(
    block_ctx: FakeContext, block_storage: FakeStorage
) -> None:
    block_storage.path_for("file://in.csv").write_text("ada,grace")

    output = await call_block(NoopConverter(), PAIR, block_ctx)

    assert block_storage.path_for("file://out.csv").read_text() == "ada,grace"
    assert output.model_dump() == {"source": "file://in.csv", "target": "file://out.csv", "bytes_written": 9}
    assert block_ctx.log.messages() == ["conversion written"]


async def test_a_source_that_is_not_there_is_rejected(block_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(NoopConverter(), PAIR, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "there is nothing at file://in.csv to convert" in raised.value.message


def test_an_unsupported_pair_is_refused_at_apply_and_names_what_is_supported() -> None:
    config = NoopConverter.config_model.model_validate(PAIR | {"to": "z"})

    assert NoopConverter().check_config(config) == ["convert.noop does not convert a to z (a to b)"]


async def test_an_unsupported_pair_that_reaches_a_run_is_rejected(block_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(NoopConverter(), PAIR | {"to": "z"}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "does not convert a to z" in raised.value.message


READINGS: list[JsonValue] = [
    {"station": "st-1", "status": "active"},
    {"station": "st-2", "status": "retired"},
    {"station": "st-3", "status": "active"},
]


async def test_a_map_replaces_every_element_and_the_output_is_as_long_as_the_input(
    block_ctx: FakeContext,
) -> None:
    output = await call_block(UpperMapper(), {"input": ["ada", "grace"], "program": "upper"}, block_ctx)

    assert output.model_dump() == {"value": ["ADA", "GRACE"]}


@pytest.mark.parametrize(
    ("value", "named"),
    [({"name": "ada"}, "an object"), ("ada", "a string"), (True, "a boolean"), (7, "a number")],
    ids=["object", "string", "boolean", "number"],
)
async def test_a_map_over_an_input_that_is_not_an_array_is_refused_with_the_verbs_promise(
    value: JsonValue, named: str, block_ctx: FakeContext
) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(UpperMapper(), {"input": value, "program": "upper"}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message == (
        f"map.upper replaces every element of a list, so its input has to be a JSON array, and this one is {named}"
    )


async def test_a_null_input_is_refused_with_the_same_promise(block_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(UpperMapper(), {"input": None, "program": "upper"}, block_ctx)

    assert raised.value.message.endswith("and this one is null")


async def test_an_engine_refusing_one_element_fails_the_step_naming_the_element(block_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(UpperMapper(), {"input": ["ada", 7, "grace"], "program": "upper"}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message == "element 1: this engine upper-cases strings"


async def test_an_engine_that_returns_fewer_elements_than_it_was_given_fails_the_frames_assertion(
    block_ctx: FakeContext,
) -> None:
    """The map promise is length, so an engine that breaks it fails itself rather than shortening a list."""
    with pytest.raises(AssertionError, match="map.swallow produced 1 elements from 2"):
        await call_block(SwallowingMapper(), {"input": ["ada", "grace"], "program": "upper"}, block_ctx)


async def test_a_bad_program_fails_a_map_step_as_rejected(block_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(UpperMapper(), {"input": ["ada"], "program": "sideways"}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "'sideways' is not a case" in raised.value.message


def test_check_config_returns_the_compile_error_for_a_bad_map_program() -> None:
    config = UpperMapper.config_model.model_validate({"input": ["ada"], "program": "sideways"})

    assert UpperMapper().check_config(config) == ["'sideways' is not a case: write upper"]


async def test_a_filter_keeps_the_matching_elements_unmodified_and_in_order(block_ctx: FakeContext) -> None:
    output = await call_block(ActiveFilterer(), {"input": READINGS, "program": "active"}, block_ctx)

    assert output.model_dump()["value"] == [
        {"station": "st-1", "status": "active"},
        {"station": "st-3", "status": "active"},
    ]


async def test_a_filter_over_an_input_that_is_not_an_array_is_refused_with_the_verbs_promise(
    block_ctx: FakeContext,
) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(ActiveFilterer(), {"input": "st-1", "program": "active"}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message == (
        "filter.status keeps some of the elements of a list, so its input has to be a JSON array, "
        "and this one is a string"
    )


async def test_an_answer_that_is_not_a_boolean_is_refused_naming_the_element(block_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(ShoutingFilterer(), {"input": READINGS, "program": "active"}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message == ("filter.shout answered 'yes' for element 0, and a filter's answer is true or false")


async def test_an_engine_refusing_one_element_fails_the_filter_naming_the_element(block_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(ActiveFilterer(), {"input": [{"status": "active"}, "st-2"], "program": "active"}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message == "element 1: this engine filters objects"


async def test_a_bad_program_fails_a_filter_step_as_rejected(block_ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(ActiveFilterer(), {"input": READINGS, "program": " "}, block_ctx)

    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message == "write the status to keep"


def test_check_config_returns_the_compile_error_for_a_bad_filter_program() -> None:
    config = ActiveFilterer.config_model.model_validate({"input": READINGS, "program": " "})

    assert ActiveFilterer().check_config(config) == ["write the status to keep"]
