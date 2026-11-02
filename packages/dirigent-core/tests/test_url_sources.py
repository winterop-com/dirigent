"""Which URL fields an earlier step's output supplies, read from the unresolved config."""

import pytest
from pydantic import BaseModel

from dirigent_common import PlainUrl
from dirigent_core.engine.references import output_url_fields


class _Config(BaseModel):
    url: PlainUrl | None = None
    path: PlainUrl = "/"
    note: str = ""


SCHEMA = _Config.model_json_schema()


@pytest.mark.parametrize(
    "url",
    [
        "${steps.a.output.link}",
        "https://h/${steps.a.output.path}",
        "${steps.a.output.base}/x?page=${steps.a.output.page}",
        "${steps.a.item.output.link}",
    ],
)
def test_a_url_every_reference_of_which_reads_a_steps_output_is_supplied_by_it(url: str) -> None:
    assert output_url_fields({"url": url}, SCHEMA) == {"url"}


@pytest.mark.parametrize(
    "url",
    [
        "https://h/x",
        "${params.link}",
        "${steps.a.output.link}?x=${params.y}",
        "https://h/x?token=${steps.a.output.t}",
        "${steps.a.output.link}&token=1",
        "${steps.a.error.message}",
        "${steps.a.items}",
        "${item}",
        "${run.scratch}/x",
        "$${steps.a.output.link}",
    ],
)
def test_any_other_url_is_judged_by_its_value(url: str) -> None:
    assert output_url_fields({"url": url}, SCHEMA) == frozenset()


@pytest.mark.parametrize(
    ("for_each", "supplied"),
    [
        ("${steps.a.output.links}", True),
        ("${params.links}", False),
        (["https://h/x"], False),
        (None, False),
    ],
)
def test_an_item_is_as_good_as_what_the_fan_out_maps_over(for_each: object, supplied: bool) -> None:
    assert bool(output_url_fields({"url": "${item.link}"}, SCHEMA, for_each)) is supplied


def test_every_url_field_is_judged_and_nothing_else() -> None:
    config = {"url": "${steps.a.output.u}", "path": "${steps.a.output.p}", "note": "${steps.a.output.n}"}
    assert output_url_fields(config, SCHEMA) == {"url", "path"}
