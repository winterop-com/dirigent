"""Tests for ``convert.std``: every re-encoding it declares between json, ndjson, csv, yaml and xml."""

import json

import pytest

from dirigent_blocks.convert_std import StdConverter
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext, FakeStorage, call_block

READINGS = [
    {"station": "st-1", "region": "east", "celsius": 4.5},
    {"station": "st-2", "region": "west", "celsius": -3.0},
]

READINGS_JSON = json.dumps(READINGS, separators=(",", ":"))

READINGS_NDJSON = "".join(f"{json.dumps(row, separators=(',', ':'))}\n" for row in READINGS)

READINGS_CSV = "station,region,celsius\nst-1,east,4.5\nst-2,west,-3.0\n"


SOURCE_URI = "file://in/source"

TARGET_URI = "file://out/target"


async def convert(ctx: FakeContext, source: str, source_format: str, target_format: str) -> str:
    """Run one conversion from one object onto another, and hand back the text it wrote."""
    async with ctx.storage.open_write(SOURCE_URI) as sink:
        await sink.write(source.encode())
    await call_block(
        StdConverter(),
        {"source": SOURCE_URI, "target": TARGET_URI, "from": source_format, "to": target_format},
        ctx,
    )
    written = [chunk async for chunk in ctx.storage.open_read(TARGET_URI)]
    return b"".join(written).decode()


def test_the_engine_is_convert_std_and_needs_no_allowlist_entry() -> None:
    assert StdConverter.spec.id == "convert.std"
    assert StdConverter.spec.local_execution is False
    assert len(StdConverter.pairs) == 13


async def test_a_json_array_becomes_one_ndjson_line_per_element_and_back(ctx: FakeContext) -> None:
    lines = await convert(ctx, READINGS_JSON, "json", "ndjson")

    assert lines == READINGS_NDJSON
    assert await convert(ctx, lines, "ndjson", "json") == READINGS_JSON


async def test_blank_lines_between_records_are_skipped_rather_than_read_as_a_record(ctx: FakeContext) -> None:
    assert await convert(ctx, f"\n{READINGS_NDJSON}\n\n", "ndjson", "json") == READINGS_JSON


async def test_the_csv_header_is_the_union_of_every_rows_keys_and_a_missing_one_is_empty(
    ctx: FakeContext,
) -> None:
    """First-seen order, so a key only the second row has is a column, and the first row's cell is blank."""
    source = json.dumps([{"station": "st-1", "celsius": 4.5}, {"station": "st-2", "region": "west"}])

    assert await convert(ctx, source, "json", "csv") == "station,celsius,region\nst-1,4.5,\nst-2,,west\n"


async def test_ndjson_converts_to_the_same_csv_as_the_json_array_does(ctx: FakeContext) -> None:
    assert await convert(ctx, READINGS_NDJSON, "ndjson", "csv") == READINGS_CSV


async def test_a_value_that_is_not_a_string_is_written_as_its_json_spelling_and_null_as_nothing(
    ctx: FakeContext,
) -> None:
    source = json.dumps([{"n": 7, "flag": True, "missing": None, "text": "ada"}])

    assert await convert(ctx, source, "json", "csv") == "n,flag,missing,text\n7,true,,ada\n"


async def test_every_cell_read_out_of_a_csv_is_a_string_because_csv_carries_no_types(ctx: FakeContext) -> None:
    text = await convert(ctx, READINGS_CSV, "csv", "json")

    assert json.loads(text) == [
        {"station": "st-1", "region": "east", "celsius": "4.5"},
        {"station": "st-2", "region": "west", "celsius": "-3.0"},
    ]


async def test_csv_to_ndjson_writes_those_same_objects_one_per_line(ctx: FakeContext) -> None:
    lines = await convert(ctx, READINGS_CSV, "csv", "ndjson")

    assert [json.loads(line) for line in lines.splitlines()] == [
        {"station": "st-1", "region": "east", "celsius": "4.5"},
        {"station": "st-2", "region": "west", "celsius": "-3.0"},
    ]


async def test_a_json_value_that_is_not_an_array_is_refused_saying_what_ndjson_needs(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, '{"station": "st-1"}', "json", "ndjson")

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "json to ndjson writes one line per element" in raised.value.message
    assert "this one is an object" in raised.value.message


async def test_a_line_that_is_not_json_is_refused_by_its_line_number(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, '{"a": 1}\n\n{"b": \n', "ndjson", "json")

    assert raised.value.error_class is ErrorClass.REJECTED
    assert raised.value.message.startswith("line 3 of the input is not JSON")


async def test_a_nested_value_is_refused_naming_the_row_and_the_key(ctx: FakeContext) -> None:
    source = json.dumps([{"id": "r1"}, {"id": "r2", "meta": {"region": "east"}}])

    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, source, "json", "csv")

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "row 2 has a nested value at 'meta'" in raised.value.message


async def test_a_row_that_is_not_an_object_has_no_csv_spelling(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, '["ada"]', "json", "csv")

    assert "row 1 of the input is a string, and a csv row is a flat object" in raised.value.message


@pytest.mark.parametrize(
    ("source", "named"),
    [("7", "a number"), ("true", "a boolean"), ("null", "null"), ('"ada"', "a string")],
)
async def test_the_refusal_names_the_json_value_that_arrived_instead_of_an_array(
    ctx: FakeContext, source: str, named: str
) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, source, "json", "csv")

    assert f"this one is {named}" in raised.value.message


async def test_a_row_that_is_an_array_is_refused_as_one(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, '[["station", "region"]]', "json", "csv")

    assert "row 1 of the input is an array, and a csv row is a flat object" in raised.value.message


async def test_bytes_that_are_not_utf8_are_refused_at_the_byte_that_is_not(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    storage.path_for("file://latin.csv").write_bytes(b"name\nGr\xe6nse\n")

    with pytest.raises(BlockFailure) as raised:
        await call_block(
            StdConverter(),
            {"source": "file://latin.csv", "target": TARGET_URI, "from": "csv", "to": "json"},
            ctx,
        )

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "at byte 7" in raised.value.message
    assert "convert.std reads and writes UTF-8" in raised.value.message


async def test_source_json_that_is_not_json_at_all_is_refused(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, "not json", "json", "csv")

    assert raised.value.message.startswith("the input is not JSON")


async def test_a_row_with_more_cells_than_the_header_names_columns_is_refused(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, "a,b\n1,2\n1,2,3\n", "csv", "json")

    assert "row 2 of the csv has more cells than the header names columns" in raised.value.message


async def test_a_row_short_of_cells_reads_the_missing_ones_as_empty(ctx: FakeContext) -> None:
    assert json.loads(await convert(ctx, "a,b\n1\n", "csv", "json")) == [{"a": "1", "b": ""}]


async def test_a_header_that_repeats_a_name_is_refused_naming_it_and_its_columns(ctx: FakeContext) -> None:
    """A record key names one column, so keeping the last value of two would drop a column silently."""
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, "a,b,a\n1,2,3\n", "csv", "json")

    assert "the csv header repeats a column name: 'a' at columns 1, 3" in raised.value.message


async def test_a_header_of_unique_names_still_converts(ctx: FakeContext) -> None:
    assert json.loads(await convert(ctx, "a,b\n1,2\n", "csv", "json")) == [{"a": "1", "b": "2"}]


async def test_a_header_with_an_empty_name_is_refused_at_its_column(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, "a,,b\n1,2,3\n", "csv", "json")

    assert "the csv header has no name at column 2" in raised.value.message


SUPPORTED = (
    "csv to json, csv to ndjson, json to csv, json to ndjson, json to xml, json to yaml, "
    "ndjson to csv, ndjson to json, ndjson to yaml, xml to json, xml to ndjson, "
    "yaml to json, yaml to ndjson"
)


def test_a_pair_that_is_no_conversion_at_all_is_refused_at_apply_naming_the_ones_that_are() -> None:
    config = StdConverter.config_model.model_validate(
        {"source": SOURCE_URI, "target": TARGET_URI, "from": "csv", "to": "csv"}
    )

    assert StdConverter().check_config(config) == [f"convert.std does not convert csv to csv ({SUPPORTED})"]


def test_a_format_this_engine_never_heard_of_is_refused_the_same_way() -> None:
    config = StdConverter.config_model.model_validate(
        {"source": SOURCE_URI, "target": TARGET_URI, "from": "json", "to": "parquet"}
    )

    assert StdConverter().check_config(config) == [f"convert.std does not convert json to parquet ({SUPPORTED})"]


def test_a_supported_pair_is_passed_without_comment() -> None:
    config = StdConverter.config_model.model_validate(
        {"source": SOURCE_URI, "target": TARGET_URI, "from": "json", "to": "csv"}
    )

    assert StdConverter().check_config(config) == []


async def test_a_conversion_reads_one_object_and_writes_another_saying_how_much_it_wrote(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    rows = "".join(f"st-{number},east,{number}.5\n" for number in range(4000))
    storage.path_for("file://readings.csv").write_text(f"station,region,celsius\n{rows}")

    output = await call_block(
        StdConverter(),
        {"source": "file://readings.csv", "target": "file://out/readings.ndjson", "from": "csv", "to": "ndjson"},
        ctx,
    )

    written = storage.path_for("file://out/readings.ndjson").read_text()
    lines = written.splitlines()
    assert output.model_dump() == {
        "source": "file://readings.csv",
        "target": "file://out/readings.ndjson",
        "bytes_written": len(written.encode()),
    }
    assert len(lines) == 4000
    assert json.loads(lines[0]) == {"station": "st-0", "region": "east", "celsius": "0.5"}
    assert json.loads(lines[-1]) == {"station": "st-3999", "region": "east", "celsius": "3999.5"}


async def test_a_source_that_is_not_there_is_refused_rather_than_converted(
    ctx: FakeContext,
) -> None:
    with pytest.raises(BlockFailure) as raised:
        await call_block(
            StdConverter(),
            {"source": "file://missing.csv", "target": TARGET_URI, "from": "csv", "to": "json"},
            ctx,
        )

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "there is nothing at file://missing.csv to convert" in raised.value.message


CONFIG_YAML = """\
name: daily-load
schedule: 0 3 * * *
targets:
- warehouse
- archive
retries: 3
paused: false
window: null
"""

CONFIG_JSON = json.dumps(
    {
        "name": "daily-load",
        "schedule": "0 3 * * *",
        "targets": ["warehouse", "archive"],
        "retries": 3,
        "paused": False,
        "window": None,
    },
    separators=(",", ":"),
)

READINGS_YAML = "---\nstation: st-1\nregion: east\ncelsius: 4.5\n---\nstation: st-2\nregion: west\ncelsius: -3.0\n"

FEED_XML = (
    "<?xml version='1.0' encoding='utf-8'?>\n"
    '<feed source="stations">'
    '<reading station="st-1"><region>east</region><celsius>4.5</celsius></reading>'
    '<reading station="st-2"><region>west</region><celsius>-3.0</celsius></reading>'
    "</feed>\n"
)

FEED_JSON = json.dumps(
    {
        "feed": {
            "@source": "stations",
            "reading": [
                {"@station": "st-1", "region": "east", "celsius": "4.5"},
                {"@station": "st-2", "region": "west", "celsius": "-3.0"},
            ],
        }
    },
    separators=(",", ":"),
)


async def test_a_yaml_document_is_one_value_so_a_config_becomes_the_object_it_describes(
    ctx: FakeContext,
) -> None:
    assert await convert(ctx, CONFIG_YAML, "yaml", "json") == CONFIG_JSON


async def test_json_to_yaml_writes_that_one_value_back_as_one_block_style_document(ctx: FakeContext) -> None:
    assert await convert(ctx, CONFIG_JSON, "json", "yaml") == CONFIG_YAML


async def test_json_to_yaml_to_json_is_the_document_it_started_as(ctx: FakeContext) -> None:
    document = await convert(ctx, CONFIG_JSON, "json", "yaml")

    assert await convert(ctx, document, "yaml", "json") == CONFIG_JSON


async def test_a_yaml_stream_is_one_document_per_ndjson_line_and_back(ctx: FakeContext) -> None:
    assert await convert(ctx, READINGS_YAML, "yaml", "ndjson") == READINGS_NDJSON
    assert await convert(ctx, READINGS_NDJSON, "ndjson", "yaml") == READINGS_YAML


async def test_a_yaml_stream_of_more_than_one_document_has_no_single_json_value(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, READINGS_YAML, "yaml", "json")

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "the input is a YAML stream of 2 documents" in raised.value.message
    assert "convert it to ndjson" in raised.value.message


@pytest.mark.parametrize(
    ("source", "refusal"),
    [
        ("window:\n  start: 2024-01-05\n", "the YAML value at $.window.start is a date"),
        ("at: 2024-01-05 03:00:00\n", "the YAML value at $.at is a timestamp"),
        ("regions: !!set\n  ? east\n", "the YAML value at $.regions is a set"),
        ("blob: !!binary aGk=\n", "the YAML value at $.blob is binary"),
        ("station: !Station {code: st-1}\n", "the YAML value at $.station is tagged '!Station'"),
        ("ratio: .nan\n", "the YAML number at $.ratio is nan"),
        ("counts:\n  1: east\n", "the YAML mapping at $.counts is keyed by 1"),
    ],
)
async def test_a_yaml_value_json_cannot_spell_is_refused_naming_its_path(
    ctx: FakeContext, source: str, refusal: str
) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, source, "yaml", "json")

    assert raised.value.error_class is ErrorClass.REJECTED
    assert refusal in raised.value.message


async def test_yaml_that_is_not_yaml_at_all_is_refused_where_the_loader_stops(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, "a: [1, 2\nb: 3\n", "yaml", "json")

    assert raised.value.message.startswith("the input is not YAML")


async def test_an_element_is_an_object_an_attribute_is_an_at_key_and_a_repeated_tag_is_a_list(
    ctx: FakeContext,
) -> None:
    assert await convert(ctx, FEED_XML, "xml", "json") == FEED_JSON


async def test_json_to_xml_writes_the_document_that_mapping_reads(ctx: FakeContext) -> None:
    assert await convert(ctx, FEED_JSON, "json", "xml") == FEED_XML


async def test_json_to_xml_to_json_is_the_document_it_started_as(ctx: FakeContext) -> None:
    document = await convert(ctx, FEED_JSON, "json", "xml")

    assert await convert(ctx, document, "xml", "json") == FEED_JSON


async def test_an_element_with_no_children_is_its_text_and_an_empty_one_is_null(ctx: FakeContext) -> None:
    text = await convert(ctx, "<row><station>st-1</station><region/></row>", "xml", "json")

    assert json.loads(text) == {"row": {"station": "st-1", "region": None}}


async def test_text_beside_attributes_is_the_text_key_and_survives_the_round_trip(ctx: FakeContext) -> None:
    source = json.dumps({"row": {"@station": "st-1", "#text": "east"}}, separators=(",", ":"))

    assert await convert(ctx, await convert(ctx, source, "json", "xml"), "xml", "json") == source


async def test_the_records_of_xml_to_ndjson_are_the_roots_children(ctx: FakeContext) -> None:
    lines = await convert(ctx, FEED_XML, "xml", "ndjson")

    assert [json.loads(line) for line in lines.splitlines()] == [
        {"@station": "st-1", "region": "east", "celsius": "4.5"},
        {"@station": "st-2", "region": "west", "celsius": "-3.0"},
    ]


async def test_mixed_content_is_refused_naming_the_element_it_is_in(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, "<feed><reading>4.5<region>east</region></reading></feed>", "xml", "json")

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "the element at feed/reading[1] has text beside its child elements" in raised.value.message


async def test_a_doctype_declaration_is_refused_rather_than_read(ctx: FakeContext) -> None:
    source = '<!DOCTYPE feed [<!ENTITY secret SYSTEM "file:///etc/passwd">]><feed>&secret;</feed>'

    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, source, "xml", "json")

    assert raised.value.error_class is ErrorClass.REJECTED
    assert "the input carries a <!DOCTYPE declaration" in raised.value.message


async def test_a_comment_that_says_doctype_is_a_comment_and_not_a_declaration(ctx: FakeContext) -> None:
    source = "<!-- no <!DOCTYPE here --><?xml-stylesheet href='x.xsl'?><feed><reading>4.5</reading></feed>"

    assert json.loads(await convert(ctx, source, "xml", "json")) == {"feed": {"reading": "4.5"}}


async def test_an_undefined_entity_has_nothing_to_expand_to_and_is_refused(ctx: FakeContext) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, "<feed>&secret;</feed>", "xml", "json")

    assert "the input is not XML" in raised.value.message
    assert "undefined entity" in raised.value.message


@pytest.mark.parametrize(
    ("source", "refusal"),
    [
        ('{"a":1,"b":2}', "json to xml writes one root element"),
        ('["st-1"]', "and this one is an array"),
        ('{"feed": {"reading": []}}', "the value at $.feed.reading is an empty array"),
        ('{"feed": {"#text": "x", "reading": "y"}}', "the object at $.feed has both '#text' and child keys"),
        ('{"feed": {"2nd": "x"}}', "the key '2nd' at $.feed['2nd'] is no XML name"),
        ('{"feed": {"@station": {"code": "st-1"}}}', "the value at $.feed['@station'] is an object"),
        ('{"feed": {"@station": null}}', "the attribute '@station' at $.feed is null"),
    ],
)
async def test_json_that_does_not_fit_the_xml_mapping_is_refused_naming_its_path(
    ctx: FakeContext, source: str, refusal: str
) -> None:
    with pytest.raises(BlockFailure) as raised:
        await convert(ctx, source, "json", "xml")

    assert raised.value.error_class is ErrorClass.REJECTED
    assert refusal in raised.value.message


async def test_a_namespaced_tag_keeps_element_trees_spelling_and_round_trips(ctx: FakeContext) -> None:
    text = await convert(ctx, '<feed xmlns="urn:example"><reading>4.5</reading></feed>', "xml", "json")

    assert json.loads(text) == {"{urn:example}feed": {"{urn:example}reading": "4.5"}}
    assert await convert(ctx, await convert(ctx, text, "json", "xml"), "xml", "json") == text


async def test_ten_thousand_records_stream_out_of_a_document_held_only_as_a_file(
    ctx: FakeContext, storage: FakeStorage
) -> None:
    """The document is never a value here: it is read from storage and written straight back to it."""
    with storage.path_for("file://feed.xml").open("w") as handle:
        handle.write("<feed>")
        for number in range(10_000):
            handle.write(f'<reading station="st-{number}"><celsius>{number}.5</celsius></reading>')
        handle.write("</feed>")

    output = await call_block(
        StdConverter(),
        {"source": "file://feed.xml", "target": "file://out/feed.ndjson", "from": "xml", "to": "ndjson"},
        ctx,
    )

    lines = storage.path_for("file://out/feed.ndjson").read_text().splitlines()
    assert output.model_dump()["target"] == "file://out/feed.ndjson"
    assert len(lines) == 10_000
    assert json.loads(lines[0]) == {"@station": "st-0", "celsius": "0.5"}
    assert json.loads(lines[-1]) == {"@station": "st-9999", "celsius": "9999.5"}
