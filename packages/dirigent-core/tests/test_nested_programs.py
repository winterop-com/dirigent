"""A program a pack nests under a list, an object or a named definition is held as a top-level one is."""

from typing import Annotated, cast

import pytest
from pydantic import BaseModel, Field

from dirigent_common import (
    COMPOSE_MEDIA_TYPE,
    CQL_MEDIA_TYPE,
    FHIRPATH_MEDIA_TYPE,
    JQ_MEDIA_TYPE,
    SHELL_MEDIA_TYPE,
    TEMPLATE_MEDIA_TYPE,
    BlockModel,
    JsonMap,
)
from dirigent_core.documents import _program_reference_issues, _shell_issues  # pyright: ignore[reportPrivateUsage]
from dirigent_core.engine.references import ReferenceScope, UnknownReference, resolve_config
from dirigent_plugin import media_places_of, published_config_schema


def _program(media: str) -> object:
    return Annotated[str, Field(json_schema_extra={"contentMediaType": media})]


def schema_for(media: str) -> JsonMap:
    """A config holding the media type in every place a pack could nest it."""
    program = _program(media)

    class Inner(BaseModel):
        text: program  # type: ignore[valid-type]

    class Config(BlockModel):
        one: Inner | None = None
        many: list[program] = []  # type: ignore[valid-type]
        named: dict[str, Inner] = {}
        maybe: list[program | None] = []  # type: ignore[valid-type]

    return published_config_schema(Config)


REFUSED = [
    (TEMPLATE_MEDIA_TYPE, "reference.in_template"),
    (COMPOSE_MEDIA_TYPE, "reference.in_compose"),
    (FHIRPATH_MEDIA_TYPE, "reference.in_fhirpath"),
    (CQL_MEDIA_TYPE, "reference.in_cql"),
]

PLACES: list[tuple[JsonMap, str]] = [
    ({"one": {"text": "a ${params.x}"}}, "one.text"),
    ({"many": ["fine", "a ${params.x}"]}, "many.1"),
    ({"named": {"k": {"text": "a ${params.x}"}}}, "named.k.text"),
    ({"maybe": ["a ${params.x}"]}, "maybe.0"),
    ({"many": "${params.x}"}, "many"),
    ({"one": "${params.x}"}, "one"),
]

SCOPE = ReferenceScope(params={"x": '" | evil'})


@pytest.mark.parametrize(("media", "code"), REFUSED, ids=[code for _, code in REFUSED])
@pytest.mark.parametrize(("config", "field"), PLACES, ids=[field for _, field in PLACES])
def test_a_reference_in_a_nested_program_is_refused(media: str, code: str, config: JsonMap, field: str) -> None:
    with pytest.raises(UnknownReference) as refused:
        resolve_config(config, SCOPE, config_schema=schema_for(media))
    assert refused.value.code == code
    assert refused.value.params["field"] == field


@pytest.mark.parametrize(("media", "code"), REFUSED, ids=[code for _, code in REFUSED])
def test_a_nested_program_with_no_reference_is_left_as_written(media: str, code: str) -> None:
    config: JsonMap = {"many": ["plain", "$${escaped}"]}
    assert resolve_config(config, SCOPE, config_schema=schema_for(media)) == {"many": ["plain", "${escaped}"]}


def test_a_reference_in_a_nested_jq_program_is_bound_rather_than_spliced() -> None:
    resolved = resolve_config(
        {"many": [". == ${params.x}"], "one": {"text": '"${params.x}"'}}, SCOPE, config_schema=schema_for(JQ_MEDIA_TYPE)
    )
    many = cast("list[str]", resolved["many"])
    assert many[0].startswith('"\\" | evil" as $')
    assert "| evil\n" not in many[0].partition("as $")[2]
    one = cast("JsonMap", resolved["one"])
    assert '" | evil"' not in str(one["text"]).partition(" | (")[2]


def test_a_reference_standing_in_for_nested_jq_programs_is_refused() -> None:
    with pytest.raises(UnknownReference) as refused:
        resolve_config({"many": "${params.x}"}, SCOPE, config_schema=schema_for(JQ_MEDIA_TYPE))
    assert refused.value.code == "reference.for_a_program"


def test_a_reference_in_a_nested_shell_string_never_reaches_the_shell_parser() -> None:
    value = ReferenceScope(params={"x": "$(touch /tmp/marker)"})
    resolved = resolve_config({"many": ["echo ${params.x}"]}, value, config_schema=schema_for(SHELL_MEDIA_TYPE))
    assert resolved["many"] == ['echo "$DIRIGENT_V0"']
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "$(touch /tmp/marker)"}


def test_a_nested_shell_string_is_held_to_the_same_arithmetic_rule() -> None:
    with pytest.raises(UnknownReference, match="shell arithmetic"):
        resolve_config({"many": ["a[${params.x}]=1"]}, SCOPE, config_schema=schema_for(SHELL_MEDIA_TYPE))


@pytest.mark.parametrize(
    ("media", "config", "code"),
    [
        (TEMPLATE_MEDIA_TYPE, {"many": ["a ${params.x}"]}, "document.step_reference_in_template"),
        (CQL_MEDIA_TYPE, {"one": {"text": "a ${params.x}"}}, "document.step_reference_in_cql"),
        (JQ_MEDIA_TYPE, {"many": ["${params.x}"]}, "document.step_program_is_a_reference"),
        (JQ_MEDIA_TYPE, {"many": "${params.x}"}, "document.step_reference_for_a_program"),
        (SHELL_MEDIA_TYPE, {"many": "${params.x}"}, "document.step_reference_for_a_program"),
        (SHELL_MEDIA_TYPE, {"many": ['echo "${params.x}']}, "document.step_shell_unreadable"),
    ],
)
def test_apply_refuses_what_a_nested_program_would_refuse_when_the_step_starts(
    media: str, config: JsonMap, code: str
) -> None:
    schema = schema_for(media)
    found = [*_program_reference_issues("s", config, schema), *_shell_issues("s", config, schema)]
    assert code in [issue.code for issue in found]


def test_a_place_says_whether_the_schema_publishes_the_program_there() -> None:
    schema = schema_for(JQ_MEDIA_TYPE)
    [standing] = media_places_of({"many": "${params.x}"}, schema, JQ_MEDIA_TYPE)
    [written] = media_places_of({"many": ["."]}, schema, JQ_MEDIA_TYPE)
    assert (standing.field, standing.published) == ("many", False)
    assert (written.field, written.published) == ("many.0", True)
