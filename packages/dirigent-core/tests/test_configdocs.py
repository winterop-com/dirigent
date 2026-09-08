"""The settings reference and the scaffolded example file, both generated from the model."""

from pathlib import Path

import yaml

from dirigent_core.config import Settings
from dirigent_core.configdocs import (
    PAGE_PATH,
    SCAFFOLDED,
    described,
    environment_name,
    example_document,
    project_document,
    render,
)

#: The repository root, above every package.
ROOT = Path(__file__).resolve().parents[3]

REGENERATE = "make docs-settings"


def test_every_setting_says_what_it_does() -> None:
    """The generated file is only as good as the descriptions, so an empty one fails here."""
    thin = [name for name in Settings.model_fields if len(described(name)) < 20]
    assert thin == [], f"these settings need a description worth reading: {thin}"


def test_the_reference_page_matches_the_model() -> None:
    page = ROOT / PAGE_PATH
    assert page.is_file(), f"{PAGE_PATH} is missing; run `{REGENERATE}`"
    assert page.read_text() == render(), f"{PAGE_PATH} no longer matches the settings model; run `{REGENERATE}`"


def test_the_reference_page_holds_every_setting_once() -> None:
    page = (ROOT / PAGE_PATH).read_text()
    for name in Settings.model_fields:
        assert f"| `{name}` |" in page
        assert environment_name(name) in page


def test_the_example_file_is_read_and_never_loaded() -> None:
    """Every line is a comment, so the file cannot change an instance by being beside it."""
    document = example_document()
    assert yaml.safe_load(document) is None
    for name in Settings.model_fields:
        assert f"# {name}: " in document, f"{name} is missing from the example file"
        assert environment_name(name) in document


def test_the_example_file_carries_the_default_a_setting_actually_has() -> None:
    document = example_document()
    assert '# database_url: "sqlite+aiosqlite:///./.dirigent/state/dirigent.db"' in document
    assert "# worker_concurrency: 8" in document
    assert "# scheduler_enabled: true" in document
    assert "# worker_tags: []" in document


def test_the_project_file_sets_only_what_a_project_is_likely_to_change() -> None:
    """A short file someone edits, with the long one beside it: the pair is the point."""
    loaded = yaml.safe_load(project_document())
    assert set(loaded) == set(SCAFFOLDED)
    assert Settings(**loaded).worker_concurrency == 8
    assert "dirigent.example.yaml" in project_document()


def test_the_project_file_can_name_a_value_of_its_own() -> None:
    assert yaml.safe_load(project_document(worker_concurrency=4))["worker_concurrency"] == 4


def test_the_concurrency_setting_says_what_the_number_counts() -> None:
    """It reads as runs or as pipelines to everyone who has not read the engine."""
    description = described("worker_concurrency")
    assert "attempts" in description


def test_a_reference_entry_says_what_a_setting_is_and_stops() -> None:
    """A table cell is one line, and tuning advice is a page of operations, not a cell.

    The rest of the docstring is not deleted; it stays where somebody reading the field will
    find it, and how to choose a number lives in operations beside the arithmetic.
    """
    entry = described("worker_concurrency")
    whole = Settings.model_fields["worker_concurrency"].description or ""

    assert entry.endswith("."), "a cell holds a sentence"
    assert len(entry) < len(whole) / 2, "the whole docstring is in the cell"
    assert "database_pool_size" in whole, "and the rest of it is still there to read"
