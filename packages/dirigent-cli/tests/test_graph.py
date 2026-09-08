"""The rendered shape of a pipeline: roots at the margin, each step under what it waits for."""

from pathlib import Path
from typing import Any

import yaml

from dirigent_cli.graph import GraphStep, render_graph, steps_of_document

EXAMPLES = Path(__file__).resolve().parents[3] / "examples"


def drawn(name: str) -> list[str]:
    """Render one example's shape, straight from the document a person wrote."""
    document: Any = yaml.safe_load((EXAMPLES / name).read_text())
    return render_graph(steps_of_document(document))


def test_a_chain_is_drawn_as_a_chain() -> None:
    assert drawn("graph/linear.yaml") == [
        "fetch  (http.request)",
        "  archive  (storage.copy)",
        "    report  (shell.run)",
    ]


def test_roots_sit_at_the_margin_and_the_step_joining_them_sits_under_the_last() -> None:
    assert drawn("graph/parallel-sleep.yaml") == [
        "slow  (time.sleep)",
        "medium  (time.sleep)",
        "quick  (time.sleep)",
        "  report  (shell.run)  also after slow, medium",
    ]


def test_a_rule_other_than_the_default_is_named_and_the_default_is_not() -> None:
    assert drawn("failure/error-handler.yaml") == [
        "load_batch  (http.request)",
        "  notify_failure  (http.request)  when one_failed",
        "  publish_success  (shell.run)",
        "    release_lock  (http.request)  also after notify_failure  when all_done",
    ]


def test_a_step_is_drawn_once_however_many_steps_it_waits_for() -> None:
    """Duplicating a step under each dependency would show a graph the document does not have."""
    steps = [
        GraphStep(name="a", block="test.one"),
        GraphStep(name="b", block="test.one"),
        GraphStep(name="join", block="test.two", depends_on=("a", "b")),
    ]
    lines = render_graph(steps)
    assert sum(1 for line in lines if "join" in line) == 1
    assert lines == ["a  (test.one)", "b  (test.one)", "  join  (test.two)  also after a"]


def test_a_dependency_that_is_not_a_step_is_not_drawn_as_one() -> None:
    steps = [GraphStep(name="only", block="test.one", depends_on=("gone",))]
    assert render_graph(steps) == ["only  (test.one)"]


def test_a_cycle_is_still_drawn_rather_than_swallowed() -> None:
    """Validation refuses one, but a renderer that silently drew nothing would be worse."""
    steps = [
        GraphStep(name="a", block="test.one", depends_on=("b",)),
        GraphStep(name="b", block="test.one", depends_on=("a",)),
    ]
    assert len(render_graph(steps)) == 2


def test_a_document_with_no_steps_draws_nothing() -> None:
    assert render_graph(steps_of_document({})) == []
    assert steps_of_document({"steps": "not a mapping"}) == []


def test_a_step_body_that_is_not_a_mapping_still_names_its_step() -> None:
    assert steps_of_document({"steps": {"broken": None}}) == [GraphStep(name="broken", block="-")]
