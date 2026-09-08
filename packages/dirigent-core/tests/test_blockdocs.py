"""The block reference page is a function of the catalog, and this is what keeps it one."""

from pathlib import Path

import pytest

from dirigent_client.schemas import BlockEntry, BlockKind, Catalog, SurfaceEntry
from dirigent_core.blockdocs import PAGE_PATH, render
from dirigent_core.plugins import load_plugin_host

#: The repository root, above every package.
ROOT = Path(__file__).resolve().parents[3]

#: Printed on the failure that says the page and the catalog disagree.
REGENERATE = "make docs-blocks"


def entry(**overrides: object) -> BlockEntry:
    """Build one catalog entry, defaulting everything the test does not care about."""
    fields: dict[str, object] = {
        "id": "toy.echo",
        "kind": BlockKind.OPERATOR,
        "summary": "Echo a value.",
        "group": "toy",
        "plugin": "toy",
    }
    return BlockEntry.model_validate({**fields, **overrides})


def catalog(*entries: BlockEntry, notifiers: list[SurfaceEntry] | None = None) -> Catalog:
    """Build a catalog holding exactly the entries a test wants to see rendered."""
    return Catalog(plugins=["toy"], blocks=list(entries), notifiers=notifiers or [])


# -- the page's shape ------------------------------------------------------------


def test_the_page_says_it_is_generated_before_it_says_anything_else() -> None:
    page = render(catalog(entry()))
    assert page.startswith("<!-- Generated"), "an editable-looking generated file gets edited"
    assert "# Block reference" in page
    assert page.endswith("\n")


def test_every_block_appears_in_the_index_and_in_its_own_section() -> None:
    page = render(catalog(entry(), entry(id="toy.tick", kind=BlockKind.SENSOR, summary="Tick.")))
    assert "| [`toy.echo`](#toyecho) | operator | toy | Echo a value. | `toy` |" in page
    assert "| [`toy.tick`](#toytick) | sensor | toy | Tick. | `toy` |" in page
    assert "### `toy.echo`" in page
    assert "### `toy.tick`" in page


def test_the_index_says_the_group_a_block_declares_rather_than_the_half_of_its_id() -> None:
    page = render(catalog(entry(id="map.jq", group="transform", summary="Map.")))
    assert "| [`map.jq`](#mapjq) | operator | transform | Map. | `toy` |" in page


def test_operators_and_sensors_are_separated_because_they_are_different_contracts() -> None:
    page = render(catalog(entry(), entry(id="toy.tick", kind=BlockKind.SENSOR, summary="Tick.")))
    assert page.index("## Operators") < page.index("### `toy.echo`") < page.index("## Sensors")


# -- the properties line ---------------------------------------------------------


def test_a_block_that_runs_code_on_the_worker_says_so_where_nobody_can_miss_it() -> None:
    page = render(catalog(entry(local_execution=True)))
    assert "**Runs code on the worker**" in page
    assert "allowlist" in page


def test_idempotence_is_stated_either_way_rather_than_only_when_true() -> None:
    assert "Not idempotent." in render(catalog(entry()))
    assert "Idempotent." in render(catalog(entry(idempotent=True)))


@pytest.mark.parametrize(
    ("seconds", "rendered"),
    [(30.0, "30s"), (60.0, "1m"), (300.0, "5m"), (3600.0, "1h"), (86400.0, "24h"), (2.5, "2.5s")],
)
def test_a_cadence_is_written_the_way_a_document_would_write_it(seconds: float, rendered: str) -> None:
    page = render(catalog(entry(default_poll_seconds=seconds)))
    assert f"Polls every {rendered}" in page


def test_a_deadline_is_reported_when_the_block_declares_one() -> None:
    page = render(catalog(entry(kind=BlockKind.SENSOR, default_deadline_seconds=3600.0)))
    assert "Gives up after 1h" in page


# -- the schema tables -----------------------------------------------------------


def test_a_block_with_no_fields_says_so_rather_than_printing_an_empty_table() -> None:
    assert "_No fields._" in render(catalog(entry()))


def test_a_required_field_is_marked_and_carries_no_default() -> None:
    schema = {"properties": {"uri": {"type": "string", "description": "Where."}}, "required": ["uri"]}
    page = render(catalog(entry(config_schema=schema)))
    assert "| `uri` | `string` | yes |  | Where. |" in page


def test_an_optional_field_shows_the_default_it_actually_has() -> None:
    schema = {"properties": {"pull": {"type": "boolean", "default": False}}}
    assert "| `pull` | `boolean` |  | `false` | -- |" in render(catalog(entry(config_schema=schema)))


def test_a_union_reads_as_prose_because_a_pipe_would_end_the_table_cell() -> None:
    schema = {"properties": {"url": {"anyOf": [{"type": "string"}, {"type": "null"}]}}}
    rendered = render(catalog(entry(config_schema=schema)))
    assert "`string or null`" in rendered
    assert "| null` |" not in rendered.replace("or null` |", "")


def test_a_list_an_object_and_an_enum_each_render_as_what_they_are() -> None:
    schema = {
        "properties": {
            "codes": {"type": "array", "items": {"type": "integer"}},
            "headers": {"type": "object", "additionalProperties": {"type": "string"}},
            "labels": {"type": "object"},
            "method": {"enum": ["GET", "POST"]},
        }
    }
    page = render(catalog(entry(config_schema=schema)))
    assert "`integer[]`" in page
    assert "`object of string`" in page
    assert "| `labels` | `object` |" in page
    assert '`"GET" or "POST"`' in page


def test_a_reference_is_followed_into_the_schemas_own_definitions() -> None:
    schema = {
        "properties": {"level": {"$ref": "#/$defs/Level"}},
        "$defs": {"Level": {"enum": ["debug", "info"]}},
    }
    assert '`"debug" or "info"`' in render(catalog(entry(config_schema=schema)))


def test_a_format_is_carried_because_it_is_half_the_type() -> None:
    schema = {"properties": {"day": {"type": "string", "format": "date"}}}
    assert "`string (date)`" in render(catalog(entry(config_schema=schema)))


def test_a_description_is_flattened_onto_one_line_and_its_pipes_escaped() -> None:
    schema = {"properties": {"x": {"type": "string", "description": "one\n  two | three"}}}
    assert "one two \\| three" in render(catalog(entry(config_schema=schema)))


# -- the other surfaces ----------------------------------------------------------


def test_the_non_block_surfaces_are_listed_and_an_empty_one_says_so() -> None:
    page = render(catalog(entry(), notifiers=[SurfaceEntry(id="log", plugin="builtin")]))
    assert "| `log` | `builtin` |" in page
    assert "_None installed._" in page, "an instance with no storage package should say so"


# -- the page that is checked in -------------------------------------------------


def test_the_checked_in_page_matches_the_installed_catalog() -> None:
    """Adding a field to a block updates this page or breaks the build."""
    page = ROOT / PAGE_PATH
    assert page.is_file(), f"{PAGE_PATH} is missing; run `{REGENERATE}`"
    assert page.read_text() == render(load_plugin_host().catalog()), (
        f"{PAGE_PATH} no longer matches the installed catalog; run `{REGENERATE}`"
    )


def test_the_page_documents_every_block_this_workspace_installs() -> None:
    text = (ROOT / PAGE_PATH).read_text()
    for block in load_plugin_host().catalog().blocks:
        assert f"### `{block.id}`" in text
