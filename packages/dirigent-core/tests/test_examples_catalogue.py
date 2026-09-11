"""Tests for the installed example catalogue: what the host reads off a plugin's shelves."""

import logging
from collections.abc import Sequence
from importlib.resources.abc import Traversable
from pathlib import Path

import pytest

from dirigent_core.examples import STARTER_TAG, ExampleEntry
from dirigent_core.plugins import PluginHost, UnknownExample, load_plugin_host
from dirigent_plugin import extension

#: A group no distribution registers, so a test sees only the plugins it passes in.
NO_GROUP = "dirigent.plugins.none"

STARTER = """\
# A teaching comment, which a copy of this document keeps.
format: dirigent/v1
kind: pipeline
code: fetch-and-post
name: Fetch and post
description: Fetch a payload and post it on.
tags: [recipes, http, starter]
requires:
  connections: [warehouse]
steps:
  fetch: {uses: http.request, with: {url: https://postman-echo.com/get}}
  post: {uses: webhook.post, needs: [fetch], with: {url: https://postman-echo.com/post}}
"""

CARRYING = """\
format: dirigent/v1
kind: pipeline
code: carries-a-connection
description: Carries what it needs, so an instance refuses to store it.
tags: [recipes, http]
connections:
  echo: {kind: http, config: {base_url: https://postman-echo.com}}
steps:
  fetch: {uses: http.request, with: {url: https://postman-echo.com/get}}
"""

BROKEN = "format: dirigent/v1\nsteps: [: :\n"

NOT_A_DOCUMENT = "kind: connections\nechoes: {}\n"


class ShelvesPlugin:
    """A plugin carrying one shelves root, counting how often the host asks for it."""

    def __init__(self, root: Path) -> None:
        """Hold the root, with nothing read yet."""
        self.root = root
        self.asked = 0

    @extension
    def examples(self) -> Sequence[Traversable]:
        """Answer with the one root, and record that the hook ran."""
        self.asked += 1
        return [self.root]


@pytest.fixture
def shelves(tmp_path: Path) -> Path:
    """Write two shelves: a starter and a carrying document, plus two files to pass over."""
    (tmp_path / "recipes").mkdir()
    (tmp_path / "recipes" / "fetch-and-post.yaml").write_text(STARTER)
    (tmp_path / "recipes" / "carries.yaml").write_text(CARRYING)
    (tmp_path / "queues").mkdir()
    (tmp_path / "queues" / "broken.yaml").write_text(BROKEN)
    (tmp_path / "connections.yaml").write_text(NOT_A_DOCUMENT)
    (tmp_path / "README.md").write_text("# the shelves\n")
    return tmp_path


def catalogue(host: PluginHost) -> list[ExampleEntry]:
    """Read the entries one plugin named `shelves` carries."""
    return [entry for entry in host.examples() if entry.plugin == "shelves"]


def test_the_catalogue_reads_every_document_on_every_shelf(shelves: Path) -> None:
    host = load_plugin_host(group=NO_GROUP, extra={"shelves": ShelvesPlugin(shelves)})
    assert [(entry.shelf, entry.code) for entry in catalogue(host)] == [
        ("recipes", "carries-a-connection"),
        ("recipes", "fetch-and-post"),
    ]


def test_an_entry_carries_what_a_reader_of_it_renders(shelves: Path) -> None:
    host = load_plugin_host(group=NO_GROUP, extra={"shelves": ShelvesPlugin(shelves)})
    entry = host.example("fetch-and-post")
    assert entry.name == "Fetch and post"
    assert entry.description == "Fetch a payload and post it on."
    assert entry.tags == ["recipes", "http", STARTER_TAG]
    assert entry.requires.connections == ["warehouse"]
    assert entry.plugin == "shelves"
    assert entry.path == "recipes/fetch-and-post.yaml"
    assert entry.starter is True
    assert entry.carries == []
    assert entry.source.startswith("# A teaching comment")


def test_a_document_that_carries_a_connection_is_listed_saying_so(shelves: Path) -> None:
    host = load_plugin_host(group=NO_GROUP, extra={"shelves": ShelvesPlugin(shelves)})
    entry = host.example("carries-a-connection")
    assert entry.carries == ["connections"]
    assert entry.starter is False


def test_a_file_that_does_not_parse_is_passed_over_with_one_warning(
    shelves: Path, caplog: pytest.LogCaptureFixture
) -> None:
    host = load_plugin_host(group=NO_GROUP, extra={"shelves": ShelvesPlugin(shelves)})
    with caplog.at_level(logging.WARNING, logger="dirigent_core.examples"):
        host.examples()
    passed_over = [record.getMessage() for record in caplog.records]
    assert len(passed_over) == 2
    assert any("queues/broken.yaml" in message and "shelves" in message for message in passed_over)
    assert any("connections.yaml" in message for message in passed_over)


def test_two_plugins_may_carry_the_same_code_and_the_lookup_says_which(shelves: Path) -> None:
    host = load_plugin_host(
        group=NO_GROUP,
        extra={"shelves": ShelvesPlugin(shelves), "other": ShelvesPlugin(shelves)},
    )
    assert len(host.examples()) == 4
    with pytest.raises(UnknownExample, match="'other' and 'shelves'"):
        host.example("fetch-and-post")


def test_a_second_document_with_one_code_in_one_plugin_is_passed_over(
    shelves: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (shelves / "recipes" / "again.yaml").write_text(STARTER)
    host = load_plugin_host(group=NO_GROUP, extra={"shelves": ShelvesPlugin(shelves)})
    with caplog.at_level(logging.WARNING, logger="dirigent_core.examples"):
        entries = catalogue(host)
    assert [entry.path for entry in entries if entry.code == "fetch-and-post"] == ["recipes/again.yaml"]
    assert any("two examples with the code" in record.getMessage() for record in caplog.records)


def test_a_code_nothing_carries_names_itself_in_the_refusal(shelves: Path) -> None:
    host = load_plugin_host(group=NO_GROUP, extra={"shelves": ShelvesPlugin(shelves)})
    with pytest.raises(UnknownExample, match="'nothing-here'"):
        host.example("nothing-here")


def test_the_shelves_are_not_walked_until_something_asks(shelves: Path) -> None:
    plugin = ShelvesPlugin(shelves)
    host = load_plugin_host(group=NO_GROUP, extra={"shelves": plugin})
    assert plugin.asked == 0
    host.examples()
    host.examples()
    assert plugin.asked == 1


def test_the_installed_corpus_is_discovered_through_the_entry_point() -> None:
    host = load_plugin_host()
    codes = {entry.code for entry in host.examples() if entry.plugin == "examples"}
    assert "hello-world" in codes
