"""Every document under examples/ must stay loadable, valid, and byte-stable, forever."""

from pathlib import Path

import pytest

from dirigent_core.documents import TriggerTarget, load_text, to_yaml, validate_against_catalog
from dirigent_core.engine.definition import PipelineDefinition, TriggersDefinition
from dirigent_core.plugins import load_plugin_host

#: The examples directory lives at the repository root, above every package.
EXAMPLES = Path(__file__).resolve().parents[3] / "examples"

#: Connections the examples reference by name; examples/connections.yaml defines them.
EXAMPLE_CONNECTIONS = (
    "postman-echo",
    "modelling-api",
    "odk-central",
    "ops-webhook",
    "artifacts",
    "warehouse-read",
    "orders-topic",
    "shop-queue",
    "build-daemon",
    "ghcr",
)

#: Pipelines the examples compose with, which a composing document requires by name.
EXAMPLE_PIPELINES = (
    "composition-child",
    "pipeline-run-child",
    "who-gho-indicators-to-parquet",
    "wikidata-country-reference",
)

#: Named schemas the examples reference by code; examples/schemas/ defines them. A carried
#: schema satisfies its own reference, so only the instance-held codes need to appear here.
EXAMPLE_SCHEMAS = (
    "dhis2-data-elements",
    "dhis2-number-data-elements",
    "dhis2-org-units",
    "dhis2-system-info",
    "ou-record",
)

#: Files under examples/ that are not pipeline documents.
NOT_DOCUMENTS = frozenset({"connections.yaml"})


def documents(directory: Path) -> list[Path]:
    """List the pipeline documents in one examples directory, in a stable order."""
    return sorted(path for path in directory.glob("*.yaml") if path.name not in NOT_DOCUMENTS)


def ids(paths: list[Path]) -> list[str]:
    """Name each parametrised case after the file it reads, so a failure says which."""
    return [path.name for path in paths]


#: The topic shelves, each a directory with its own README index.
SHELVES = (
    "composition",
    "demo",
    "docker",
    "execute",
    "failure",
    "git",
    "graph",
    "open-data",
    "patterns",
    "queues",
    "recipes",
    "s3",
    "sensors",
    "sql",
    "transform",
    "triggers",
    "validate",
)


def is_triggers_document(path: Path) -> bool:
    """Say whether a file is a triggers document, without paying to build the model."""
    return isinstance(load_text(path.read_text()), TriggersDefinition)


REAL = documents(EXAMPLES)
PREVIEW = documents(EXAMPLES / "preview")

#: Every document an instance is expected to accept, wherever in examples/ it sits.
RUNNABLE = [*REAL, *(path for shelf in SHELVES for path in documents(EXAMPLES / shelf))]

#: The triggers documents in the corpus, which name a pipeline rather than declaring steps.
TRIGGER_DOCUMENTS = [path for path in RUNNABLE if is_triggers_document(path)]

#: Every pipeline document an instance is expected to accept.
PIPELINES = [path for path in RUNNABLE if path not in TRIGGER_DOCUMENTS]

#: Those and the previews: what round-trips and what explains itself.
EVERY = [*RUNNABLE, *PREVIEW]


def test_the_examples_directory_is_where_the_test_expects_it() -> None:
    assert EXAMPLES.is_dir(), f"{EXAMPLES} is missing"
    assert REAL, "there are no examples to check"
    for shelf in SHELVES:
        assert documents(EXAMPLES / shelf), f"there are no {shelf} documents to check"
    assert PREVIEW, "there are no preview documents to check"


@pytest.mark.parametrize("path", PIPELINES, ids=ids(PIPELINES))
def test_an_example_validates_against_the_real_catalog(path: Path) -> None:
    definition = load_text(path.read_text())
    issues = validate_against_catalog(
        definition,
        load_plugin_host().catalog(),
        connections=EXAMPLE_CONNECTIONS,
        pipelines=EXAMPLE_PIPELINES,
        schemas=EXAMPLE_SCHEMAS,
    )
    assert issues == [], "\n".join(str(issue) for issue in issues)


@pytest.mark.parametrize("path", TRIGGER_DOCUMENTS, ids=ids(TRIGGER_DOCUMENTS))
def test_a_triggers_example_validates_against_the_pipeline_it_names(path: Path) -> None:
    """A triggers document is only checkable beside its target, so the corpus supplies one."""
    definition = load_text(path.read_text())
    assert isinstance(definition, TriggersDefinition)
    target = _example_pipeline(definition.pipeline)
    issues = validate_against_catalog(
        definition,
        load_plugin_host().catalog(),
        target=TriggerTarget(code=target.code, definition=target),
    )
    assert issues == [], "\n".join(str(issue) for issue in issues)


def _example_pipeline(code: str) -> PipelineDefinition:
    """Find the pipeline example a triggers example names, wherever in the corpus it sits."""
    for path in PIPELINES:
        definition = load_text(path.read_text())
        if definition.code == code:
            assert isinstance(definition, PipelineDefinition)
            return definition
    raise AssertionError(f"no example pipeline is coded {code!r}")


@pytest.mark.parametrize("path", TRIGGER_DOCUMENTS, ids=ids(TRIGGER_DOCUMENTS))
def test_a_triggers_example_is_refused_where_its_pipeline_is_absent(path: Path) -> None:
    """The offline check every triggers document has.

    It names a pipeline, and an instance that does not hold that pipeline refuses the document
    rather than storing a clock that fires nothing.
    """
    definition = load_text(path.read_text())
    issues = validate_against_catalog(definition, load_plugin_host().catalog())
    assert [issue.location for issue in issues] == ["pipeline"]


@pytest.mark.parametrize("path", PREVIEW, ids=ids(PREVIEW))
def test_a_preview_document_is_valid_dirigent_v1_even_without_its_adapter_pack(path: Path) -> None:
    definition = load_text(path.read_text())
    assert validate_against_catalog(definition, load_plugin_host().catalog(), check_blocks=False) == []


@pytest.mark.parametrize("path", PREVIEW, ids=ids(PREVIEW))
def test_a_preview_document_says_what_it_needs(path: Path) -> None:
    definition = load_text(path.read_text())
    assert isinstance(definition, PipelineDefinition)
    assert not definition.requires.empty, "a preview document must declare what it requires"
    issues = validate_against_catalog(definition, load_plugin_host().catalog())
    assert issues, "a preview document should be refused by an instance without its adapter pack"
    assert all(issue.location.startswith(("requires.", "steps.")) for issue in issues)


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_an_example_round_trips_through_the_canonical_form(path: Path) -> None:
    definition = load_text(path.read_text())
    exported = to_yaml(definition)
    assert to_yaml(load_text(exported)) == exported
    assert load_text(exported) == definition


@pytest.mark.parametrize("path", EVERY, ids=ids(EVERY))
def test_an_example_is_coded_after_its_file_and_explains_itself(path: Path) -> None:
    text = path.read_text()
    definition = load_text(text)
    assert definition.code == path.stem, "a document's code should match its file name"
    assert definition.description, "every example says what it is for"
    assert text.startswith("#"), "every example opens with a comment saying what it shows"


@pytest.mark.parametrize(
    "path",
    [*EVERY, EXAMPLES / "README.md", *(EXAMPLES / shelf / "README.md" for shelf in SHELVES)],
    ids=ids(EVERY) + ["README.md", *(f"{shelf}/README.md" for shelf in SHELVES)],
)
def test_no_example_contains_a_tab_or_a_trailing_space(path: Path) -> None:
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        assert "\t" not in line, f"{path.name}:{number} contains a tab"
        assert line == line.rstrip(), f"{path.name}:{number} has trailing whitespace"


def test_the_index_lists_every_example() -> None:
    index = (EXAMPLES / "README.md").read_text()
    for path in REAL:
        assert f"]({path.name})" in index, f"{path.name} is missing from examples/README.md"
    for shelf in SHELVES:
        assert f"]({shelf}/" in index or f"]({shelf})" in index, f"{shelf}/ is missing from examples/README.md"
    for path in PREVIEW:
        assert f"](preview/{path.name})" in index, f"preview/{path.name} is missing from examples/README.md"


@pytest.mark.parametrize("shelf", SHELVES)
def test_every_shelf_index_lists_every_document_on_it(shelf: str) -> None:
    index = (EXAMPLES / shelf / "README.md").read_text()
    for path in documents(EXAMPLES / shelf):
        assert f"]({path.name})" in index, f"{path.name} is missing from examples/{shelf}/README.md"
