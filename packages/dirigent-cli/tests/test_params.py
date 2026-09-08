"""Parameters on the command line: paths, schema coercion, files, and precedence."""

from pathlib import Path
from typing import Any

import pytest

from dirigent_cli.params import APPEND, ParamError, build_params, deep_merge, read_params_file, split_key

SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["day"],
    "properties": {
        "day": {"type": "string", "format": "date"},
        "code": {"type": "string"},
        "channel": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "count": {"type": "integer"},
        "ratio": {"type": "number"},
        "dry_run": {"type": "boolean"},
        "dataset": {"type": "string", "enum": ["climate", "population"]},
        "regions": {"type": "array", "items": {"type": "string"}},
        "filter": {"type": "object", "properties": {"level": {"type": "integer"}}},
        "limits": {
            "type": "object",
            "properties": {
                "max": {"type": "integer"},
                "retries": {"type": "array", "items": {"type": "integer"}},
            },
        },
        "targets": {
            "type": "array",
            "items": {"type": "object", "properties": {"host": {"type": "string"}}},
        },
        "server": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "timeout": {"type": "integer"},
                "tls": {
                    "type": "object",
                    "properties": {"verify": {"type": "boolean"}, "ca": {"type": "string"}},
                },
            },
        },
    },
}


def build(*pairs: str, files: list[Path] | None = None) -> dict[str, Any]:
    """Build parameters against the shared schema."""
    return build_params(SCHEMA, pairs=pairs, files=files or [])


@pytest.mark.parametrize(
    ("pair", "expected"),
    [
        ("count=3", {"count": 3}),
        ("count=-7", {"count": -7}),
        ("ratio=0.5", {"ratio": 0.5}),
        ("dry_run=true", {"dry_run": True}),
        ("dry_run=no", {"dry_run": False}),
        ("dry_run=1", {"dry_run": True}),
        ("day=2026-01-01", {"day": "2026-01-01"}),
        ("dataset=climate", {"dataset": "climate"}),
    ],
)
def test_a_value_is_coerced_by_the_type_the_schema_declares(pair: str, expected: dict[str, Any]) -> None:
    assert build(pair) == expected


def test_a_string_that_looks_like_a_number_stays_a_string() -> None:
    assert build("code=3") == {"code": "3"}
    assert build("code=00123") == {"code": "00123"}
    assert build("day=2026") == {"day": "2026"}


@pytest.mark.parametrize(
    ("pair", "message"),
    [
        ("count=many", "is an integer"),
        ("ratio=lots", "is a number"),
        ("dry_run=maybe", "is a boolean"),
        ("dataset=weather", "is not one of"),
    ],
)
def test_a_value_the_schema_refuses_is_refused_here(pair: str, message: str) -> None:
    with pytest.raises(ParamError, match=message):
        build(pair)


def test_an_array_is_given_whole_in_json_or_in_yaml() -> None:
    assert build('regions=["east", "west"]') == {"regions": ["east", "west"]}
    assert build("regions=[east, west]") == {"regions": ["east", "west"]}


def test_an_object_is_given_whole() -> None:
    assert build('filter={"level": 3}') == {"filter": {"level": 3}}
    assert build("filter={level: 3}") == {"filter": {"level": 3}}


def test_something_that_is_not_the_declared_shape_is_refused() -> None:
    with pytest.raises(ParamError, match="is an array"):
        build("regions=east")
    with pytest.raises(ParamError, match="is an object"):
        build("filter=3")


def test_a_dotted_key_addresses_a_nested_leaf() -> None:
    assert build("server.timeout=30") == {"server": {"timeout": 30}}
    assert build("server.tls.verify=false") == {"server": {"tls": {"verify": False}}}


def test_dotted_keys_deep_merge_rather_than_replacing_their_parent() -> None:
    built = build("server.host=example.org", "server.tls.verify=false", "server.tls.ca=/etc/ca.pem")
    assert built == {"server": {"host": "example.org", "tls": {"verify": False, "ca": "/etc/ca.pem"}}}


def test_an_unknown_path_names_where_in_the_schema_it_went_wrong() -> None:
    with pytest.raises(ParamError, match="no parameter 'nope'"):
        build("nope=1")
    with pytest.raises(ParamError, match="no parameter 'server.nope'"):
        build("server.nope=1")
    with pytest.raises(ParamError, match="it declares host, timeout, tls"):
        build("server.nope=1")


def test_an_index_addresses_one_element_of_an_array() -> None:
    assert build("regions[0]=north") == {"regions": ["north"]}
    assert build("regions[0]=north", "regions[1]=south") == {"regions": ["north", "south"]}
    assert build("limits.retries[0]=1", "limits.retries[1]=2", "limits.retries[2]=3") == {
        "limits": {"retries": [1, 2, 3]}
    }


def test_an_empty_bracket_appends() -> None:
    assert build("regions[]=north", "regions[]=south") == {"regions": ["north", "south"]}
    assert build("regions[0]=north", "regions[]=south") == {"regions": ["north", "south"]}


def test_an_index_that_exists_replaces_that_element() -> None:
    built = build("regions[0]=north", "regions[1]=south", "regions[0]=east")
    assert built == {"regions": ["east", "south"]}


def test_an_element_is_coerced_by_the_type_the_items_schema_declares() -> None:
    assert build("limits.retries[]=3") == {"limits": {"retries": [3]}}
    with pytest.raises(ParamError, match="is an integer"):
        build("limits.retries[]=many")


def test_an_index_inside_an_element_addresses_that_element_s_own_leaf() -> None:
    assert build("targets[0].host=example.org") == {"targets": [{"host": "example.org"}]}
    with pytest.raises(ParamError, match="declares no parameter 'targets\\[0\\].nope'"):
        build("targets[0].nope=x")


def test_an_index_past_the_end_is_refused_with_the_gap_named() -> None:
    with pytest.raises(ParamError, match=r"holds 0 elements, so \[5\] would leave a gap"):
        build("regions[5]=north")
    with pytest.raises(ParamError, match=r"holds 1 element, so \[2\] would leave a gap"):
        build("regions[0]=north", "regions[2]=south")


def test_a_negative_index_is_refused() -> None:
    with pytest.raises(ParamError, match="counts from the start of the array"):
        build("regions[-1]=north")
    with pytest.raises(ParamError, match="a whole number or nothing at all"):
        build("regions[first]=north")


def test_a_path_that_mixes_a_key_and_an_index_is_refused_with_the_schema_s_word() -> None:
    with pytest.raises(ParamError, match="calls 'regions' an array, so it takes an index"):
        build("regions.name=north")
    with pytest.raises(ParamError, match="calls 'server' an object, so it takes a key, not an index"):
        build("server[0]=north")


def test_a_path_is_parsed_into_keys_and_indices() -> None:
    assert split_key("regions[0]") == ["regions", 0]
    assert split_key("limits.retries[2]") == ["limits", "retries", 2]
    assert split_key("regions[]") == ["regions", APPEND]
    assert split_key("targets[0].host") == ["targets", 0, "host"]


def test_a_numeric_segment_is_refused_because_it_is_ambiguous() -> None:
    with pytest.raises(ParamError, match="cannot tell the index"):
        split_key("regions.0")
    with pytest.raises(ParamError, match=r"brackets instead \(regions\[0\]"):
        build("regions.0=east")


def test_a_malformed_key_is_refused() -> None:
    with pytest.raises(ParamError, match="key=value"):
        build("nonsense")
    with pytest.raises(ParamError, match="key=value"):
        build("=value")
    with pytest.raises(ParamError, match="empty segment"):
        split_key("server..host")


def test_an_open_schema_accepts_a_path_it_does_not_describe() -> None:
    open_schema: dict[str, Any] = {"type": "object", "additionalProperties": True}
    assert build_params(open_schema, pairs=["anything=3"]) == {"anything": 3}
    assert build_params({}, pairs=["anything=3"]) == {"anything": 3}


def test_a_file_is_refused_the_same_undeclared_key_a_flag_is(tmp_path: Path) -> None:
    path = tmp_path / "params.yaml"
    path.write_text("day: 2026-01-01\ndya: 2026-01-01\n")
    with pytest.raises(ParamError, match=r"params file .*/params\.yaml: the pipeline declares no parameter 'dya'"):
        build(files=[path])
    with pytest.raises(ParamError, match="no parameter 'dya'"):
        build("dya=2026-01-01")


def test_a_file_holding_only_declared_keys_passes(tmp_path: Path) -> None:
    path = tmp_path / "params.yaml"
    path.write_text("day: 2026-01-01\ncount: 5\n")
    assert build(files=[path]) == {"day": "2026-01-01", "count": 5}


def test_an_open_schema_accepts_an_extra_from_either_channel(tmp_path: Path) -> None:
    open_schema: dict[str, Any] = {
        "type": "object",
        "properties": {"day": {"type": "string"}},
        "additionalProperties": True,
    }
    path = tmp_path / "params.yaml"
    path.write_text("anything: 3\n")
    assert build_params(open_schema, files=[path]) == {"anything": 3}
    assert build_params(open_schema, pairs=["anything=3"]) == {"anything": 3}
    assert build_params({}, files=[path]) == {"anything": 3}


def test_a_params_file_is_read_as_yaml_or_json(tmp_path: Path) -> None:
    yaml_file = tmp_path / "params.yaml"
    yaml_file.write_text("day: 2026-01-01\ncount: 5\n")
    assert read_params_file(yaml_file) == {"day": "2026-01-01", "count": 5}

    json_file = tmp_path / "params.json"
    json_file.write_text('{"day": "2026-01-01", "count": 5}')
    assert read_params_file(json_file) == {"day": "2026-01-01", "count": 5}

    empty = tmp_path / "empty.yaml"
    empty.write_text("")
    assert read_params_file(empty) == {}


def test_a_params_file_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "params.yaml"
    path.write_text("- a\n- b\n")
    with pytest.raises(ParamError, match="mapping of parameters"):
        read_params_file(path)
    with pytest.raises(ParamError, match="could not be read"):
        read_params_file(tmp_path / "missing.yaml")


def test_flags_override_a_file_and_later_flags_override_earlier_ones(tmp_path: Path) -> None:
    path = tmp_path / "params.yaml"
    path.write_text("day: 2026-01-01\ncount: 5\nserver: {host: from-the-file, timeout: 1}\n")
    built = build("count=9", "count=11", "server.timeout=30", files=[path])
    assert built["count"] == 11
    assert built["day"] == "2026-01-01"
    assert built["server"] == {"host": "from-the-file", "timeout": 30}


def test_files_apply_in_the_order_they_were_given(tmp_path: Path) -> None:
    first = tmp_path / "one.yaml"
    first.write_text("count: 1\nday: 2026-01-01\n")
    second = tmp_path / "two.yaml"
    second.write_text("count: 2\n")
    assert build(files=[first, second])["count"] == 2
    assert build(files=[second, first])["count"] == 1


def test_an_array_replaces_rather_than_merging() -> None:
    merged = deep_merge({"regions": ["east"]}, {"regions": ["west"]})
    assert merged == {"regions": ["west"]}


def test_an_object_merges_rather_than_replacing() -> None:
    merged = deep_merge({"server": {"host": "a", "timeout": 1}}, {"server": {"timeout": 2}})
    assert merged == {"server": {"host": "a", "timeout": 2}}


def test_an_element_set_by_a_flag_replaces_that_element_of_a_file_s_array(tmp_path: Path) -> None:
    path = tmp_path / "params.yaml"
    path.write_text("day: 2026-01-01\nregions: [north, south, east]\n")
    built = build("regions[1]=west", files=[path])
    assert built["regions"] == ["north", "west", "east"]
    assert build("regions[]=west", files=[path])["regions"] == ["north", "south", "east", "west"]


def test_an_optional_string_is_read_as_a_string_rather_than_as_yaml() -> None:
    # `anyOf: [string, null]` is how every connection kind's generated schema spells an
    # optional field, and YAML would read a leading # as the start of a comment.
    assert build("channel=#ops-alerts")["channel"] == "#ops-alerts"
