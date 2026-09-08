"""The environment a suite opts into: dirigent's own variables gone, width and colour fixed."""

import os

import pytest

from dirigent_testing import CONFIGURING_PREFIXES, TEST_WIDTH, pin_terminal, scrub_configuration

# Set while the module is imported, which is before any fixture for these tests runs: a
# developer's shell would have exported it just as early.
os.environ["DIRIGENT_ANYTHING"] = "set by a developer's shell"


def test_the_fixture_takes_away_a_variable_that_was_there_first(defaults_only_environment: None) -> None:
    assert "DIRIGENT_ANYTHING" not in os.environ
    assert os.environ["COLUMNS"] == TEST_WIDTH


@pytest.mark.parametrize("name", [f"{prefix}ANYTHING" for prefix in CONFIGURING_PREFIXES])
def test_every_prefix_that_configures_dirigent_is_scrubbed(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(name, "set by a developer's shell")

    scrub_configuration(monkeypatch)

    assert name not in os.environ


def test_an_unrelated_variable_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EDITOR", "vi")

    scrub_configuration(monkeypatch)

    assert os.environ["EDITOR"] == "vi"


def test_pinning_the_terminal_fixes_width_and_colour_and_reports_the_width_it_saw_first() -> None:
    width = pin_terminal()

    assert width == pin_terminal()
    assert os.environ["COLUMNS"] == TEST_WIDTH
    assert os.environ["TERMINAL_WIDTH"] == TEST_WIDTH
    assert os.environ["NO_COLOR"] == "1"
