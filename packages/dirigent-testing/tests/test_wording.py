"""The wording check, and this workspace held to it the way a pack is held to it."""

import importlib
from pathlib import Path
from typing import Final

import pytest

from dirigent_common import Catalogue
from dirigent_testing.wording import Reading, check_pack_messages, colliding, is_prose, source_files

#: This checkout's packages, walked as one tree so a message minted in one package and read
#: in another is not read as dead.
PACKAGES: Final = Path(__file__).resolve().parents[2]

#: Every messages module the workspace holds, imported so the walk over ``Catalogue.all``
#: sees every prefix rather than only the ones some other test happened to import first.
MODULES: Final[tuple[str, ...]] = (
    "dirigent_common.messages",
    "dirigent_plugin.messages",
    "dirigent_client.messages",
    "dirigent_core.messages",
    "dirigent_server.messages",
    "dirigent_cli.messages",
    "dirigent_testing.messages",
    "dirigent_blocks.messages",
    "dirigent_block_base.messages",
    "dirigent_block_duckdb.messages",
    "dirigent_block_execute.messages",
    "dirigent_block_http.messages",
    "dirigent_block_jq.messages",
    "dirigent_block_parquet.messages",
    "dirigent_block_queues.messages",
    "dirigent_block_sql.messages",
    "dirigent_block_storage.messages",
)


def module(tmp_path: Path, name: str, body: str) -> Path:
    """Write one module into a package directory and hand back the directory.

    Args:
        tmp_path: The test's own directory.
        name: The module's file name.
        body: Its source.

    Returns:
        The directory to check, holding that one module.
    """
    (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


# What the check refuses.


def test_a_validator_raising_a_sentence_is_refused(tmp_path: Path) -> None:
    source = module(
        tmp_path,
        "config.py",
        "from pydantic import model_validator\n"
        "class C:\n"
        "    @model_validator(mode='after')\n"
        "    def _check(self):\n"
        "        raise ValueError('a window runs forwards and covers something')\n",
    )

    issues = check_pack_messages(source)

    assert len(issues) == 1
    assert "config.py:5" in issues[0]
    assert "validator _check raises" in issues[0]


def test_a_validator_raising_an_f_string_is_refused_around_its_holes(tmp_path: Path) -> None:
    """The value a sentence is written around is one hole; the words beside it are words."""
    source = module(
        tmp_path,
        "config.py",
        "from pydantic import field_validator\n"
        "class C:\n"
        "    @field_validator('x')\n"
        "    def _check(cls, value):\n"
        "        raise ValueError(f'task {value} disappeared before it could be collected')\n",
    )

    assert "'task {} disappeared before it could be collected'" in check_pack_messages(source)[0]


def test_a_validator_rendering_a_catalogued_message_is_accepted(tmp_path: Path) -> None:
    source = module(
        tmp_path,
        "config.py",
        "from pydantic import model_validator\n"
        "from acme.messages import NO_CREDENTIAL\n"
        "class C:\n"
        "    @model_validator(mode='after')\n"
        "    def _check(self):\n"
        "        raise ValueError(NO_CREDENTIAL.render(url=self.url))\n",
    )

    assert check_pack_messages(source) == []


def test_a_validator_raising_a_wire_value_is_not_read_as_a_sentence(tmp_path: Path) -> None:
    """One word is a value, not prose: a check people argue with is one nobody fixes."""
    source = module(
        tmp_path,
        "config.py",
        "from pydantic import field_validator\n"
        "class C:\n"
        "    @field_validator('x')\n"
        "    def _check(cls, value):\n"
        "        raise KeyError('dhis2')\n",
    )

    assert check_pack_messages(source) == []


def test_a_raise_outside_a_validator_is_left_to_review(tmp_path: Path) -> None:
    """An exception a package raises for itself and catches is not a refusal until it is one."""
    source = module(
        tmp_path,
        "cli.py",
        "class ParamError(Exception): pass\n"
        "def read(value):\n"
        "    raise ParamError('that is not a duration anyone could read')\n",
    )

    assert check_pack_messages(source) == []


def test_a_coded_constructor_handed_a_literal_is_refused(tmp_path: Path) -> None:
    source = module(tmp_path, "block.py", "def go():\n    raise BlockFailure('the instance refused the import')\n")

    issues = check_pack_messages(source)

    assert len(issues) == 1
    assert "BlockFailure was given" in issues[0]


def test_a_coded_constructor_handed_a_message_is_accepted(tmp_path: Path) -> None:
    source = module(tmp_path, "block.py", "def go():\n    raise BlockFailure(IMPORT_REFUSED, detail=body)\n")

    assert check_pack_messages(source) == []


# A catalogue entry nothing reads.


def test_a_message_no_source_reads_is_refused(tmp_path: Path) -> None:
    source = module(tmp_path, "messages.py", "ACME = Catalogue('acme')\nGONE = ACME.define('gone', 'it is gone')\n")

    issues = check_pack_messages(source)

    assert len(issues) == 1
    assert "GONE mints 'gone'" in issues[0]


def test_a_message_another_module_reads_is_alive(tmp_path: Path) -> None:
    module(tmp_path, "messages.py", "ACME = Catalogue('acme')\nGONE = ACME.define('gone', 'it is gone')\n")
    source = module(tmp_path, "block.py", "from acme.messages import GONE\n")

    assert check_pack_messages(source) == []


def test_a_message_named_only_inside_a_longer_name_is_still_dead(tmp_path: Path) -> None:
    """``GONE`` is not read by ``GONE_PROBES``, or one name would vouch for another."""
    module(tmp_path, "messages.py", "ACME = Catalogue('acme')\nGONE = ACME.define('gone', 'it is gone')\n")
    source = module(tmp_path, "block.py", "GONE_PROBES = 3\n")

    assert len(check_pack_messages(source)) == 1


def test_a_message_read_again_in_the_module_that_mints_it_is_alive(tmp_path: Path) -> None:
    source = module(
        tmp_path,
        "messages.py",
        "ACME = Catalogue('acme')\nGONE = ACME.define('gone', 'it is gone')\nEVERY = [GONE]\n",
    )

    assert check_pack_messages(source) == []


# Two catalogues defining one code.


def test_two_catalogues_defining_one_code_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The walk is over the whole process, so the two are put in front of it on their own."""
    monkeypatch.setattr(Catalogue, "all", [])
    Catalogue("acme").define("clash", "said once")
    Catalogue("acme").define("clash", "said twice")

    assert colliding() == ["acme.clash is defined by two catalogues: a code has exactly one owner"]


def test_a_catalogue_minted_inside_a_test_is_passed_over(monkeypatch: pytest.MonkeyPatch) -> None:
    """One cannot be unregistered, so a `test_` prefix is what keeps a suite's own out."""
    monkeypatch.setattr(Catalogue, "all", [])
    Catalogue("test_wording").define("clash", "said once")
    Catalogue("test_wording").define("clash", "said twice")

    assert colliding() == []


# What the parts do on their own.


@pytest.mark.parametrize(
    ("text", "prose"),
    [
        ("the import took nothing", True),
        ("a window runs forwards", True),
        ("dhis2", False),
        ("{}", False),
        (".. | .id?", False),
        ("GET {}", False),
    ],
)
def test_prose_is_two_words_a_person_reads(text: str, prose: bool) -> None:
    assert is_prose(text) is prose


def test_a_module_names_every_message_it_mints(tmp_path: Path) -> None:
    path = tmp_path / "messages.py"
    path.write_text("ACME = Catalogue('acme')\nONE = ACME.define('one', 'first')\nTWO = ACME.define('two', 'second')\n")

    assert Reading(path, "messages.py").minted() == {"ONE": "one", "TWO": "two"}


def test_a_directory_that_is_not_there_is_said_so(tmp_path: Path) -> None:
    assert "is not a directory" in check_pack_messages(tmp_path / "nowhere")[0]


# This workspace, held to the rule a pack is held to.


def test_every_refusal_this_workspace_makes_carries_a_code() -> None:
    """The rule proven where the catalogues are densest, by the call a pack makes."""
    for name in MODULES:
        importlib.import_module(name)

    assert check_pack_messages(PACKAGES) == []


def test_there_is_a_workspace_to_check() -> None:
    assert len(source_files(PACKAGES)) > 100
