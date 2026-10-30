"""A state directory is opened or deleted only when a checkout cannot have supplied it."""

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from dirigent_core.config import Settings
from dirigent_core.database import create_engine, ensure_sqlite_directory
from dirigent_core.statedir import (
    STATE_MODE,
    StateRefused,
    check_state,
    check_state_directory,
    clear_state_directory,
    is_state_directory,
)


def git(*argv: str, cwd: Path) -> None:
    """Run git on this test's own repository, with none of this machine's configuration."""
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    identity = ["-c", "user.name=test", "-c", "user.email=test@example.test", "-c", "protocol.file.allow=always"]
    subprocess.run(["git", *identity, *argv], cwd=cwd, env=env, check=True, capture_output=True)  # noqa: S603, S607


def honest_state(root: Path) -> Path:
    """Make a state directory the way an instance does."""
    state = root / ".dirigent" / "state"
    state.mkdir(mode=STATE_MODE, parents=True)
    (state / "dirigent.db").write_text("a database")
    (state / "artifacts").mkdir()
    return state


def committed_state(root: Path, *init: str) -> Path:
    """Commit a state directory into a repository at root."""
    root.mkdir(parents=True, exist_ok=True)
    state = honest_state(root)
    (state / "artifacts" / "kept").write_text("committed")
    git("init", "-q", *init, cwd=root)
    git("add", "-f", ".dirigent", cwd=root)
    git("commit", "-qm", "state", cwd=root)
    return state


def refusal(directory: Path) -> str:
    """Answer the code a state directory is refused with."""
    with pytest.raises(StateRefused) as refused:
        check_state_directory(directory)
    return refused.value.code


@pytest.fixture
def victim(tmp_path: Path) -> Iterator[Path]:
    """Another project's honest state, which a link may point at."""
    yield honest_state(tmp_path / "victim")


def test_only_a_directory_spelled_as_state_is_guarded() -> None:
    assert is_state_directory(Path(".dirigent/state"))
    assert is_state_directory(Path("/somewhere/.dirigent/state"))
    assert not is_state_directory(Path("/somewhere/state"))
    assert not is_state_directory(Path("/somewhere/dirigent/state"))


def test_an_honest_state_and_no_state_are_both_accepted(tmp_path: Path) -> None:
    check_state_directory(tmp_path / "absent" / ".dirigent" / "state")
    check_state_directory(honest_state(tmp_path))


def test_a_state_directory_is_created_private_whatever_the_umask(tmp_path: Path) -> None:
    """A group-writable umask must not make the second start refuse what the first one made."""
    state = tmp_path / ".dirigent" / "state"
    settings = Settings(database_url=f"sqlite+aiosqlite:///{state / 'dirigent.db'}")
    previous = os.umask(0o002)
    try:
        ensure_sqlite_directory(settings)
    finally:
        os.umask(previous)

    assert state.stat().st_mode & 0o777 == STATE_MODE
    check_state(settings)


def test_a_state_directory_that_is_a_link_is_refused(tmp_path: Path, victim: Path) -> None:
    state = tmp_path / ".dirigent" / "state"
    state.parent.mkdir()
    state.symlink_to(victim)

    assert refusal(state) == "database.state_is_a_link"


def test_a_dirigent_directory_that_is_a_link_is_refused(tmp_path: Path, victim: Path) -> None:
    (tmp_path / ".dirigent").symlink_to(victim.parent)

    assert refusal(tmp_path / ".dirigent" / "state") == "database.state_is_a_link"


def test_a_dangling_link_is_refused_before_anything_is_made_through_it(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    (tmp_path / "project" / ".dirigent").mkdir(parents=True)
    state = tmp_path / "project" / ".dirigent" / "state"
    state.symlink_to(target)
    settings = Settings(database_url=f"sqlite+aiosqlite:///{state / 'dirigent.db'}")

    with pytest.raises(StateRefused):
        create_engine(settings)

    assert not target.exists()


@pytest.mark.parametrize("name", ["dirigent.db", "dirigent.db-wal", "dirigent.db-shm", "artifacts", "work"])
def test_a_link_directly_inside_the_state_is_refused(tmp_path: Path, victim: Path, name: str) -> None:
    state = honest_state(tmp_path)
    held = state / name
    if held.is_dir():
        held.rmdir()
    held.unlink(missing_ok=True)
    held.symlink_to(victim / "dirigent.db")

    assert refusal(state) == "database.state_is_a_link"


def test_a_fifo_inside_the_state_is_refused_without_blocking(tmp_path: Path) -> None:
    state = honest_state(tmp_path)
    os.mkfifo(state / "dirigent.db-wal")

    assert refusal(state) == "database.state_is_a_link"


def test_a_state_owned_by_another_user_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = honest_state(tmp_path)
    monkeypatch.setattr(os, "getuid", lambda: os.stat(state).st_uid + 1)

    assert refusal(state) == "database.state_not_yours"


@pytest.mark.parametrize("mode", [0o770, 0o707, 0o777])
def test_a_state_others_can_write_is_refused(tmp_path: Path, mode: int) -> None:
    state = honest_state(tmp_path)
    state.chmod(mode)

    assert refusal(state) == "database.state_writable"


def test_a_readable_state_from_before_it_was_made_private_is_accepted(tmp_path: Path) -> None:
    state = honest_state(tmp_path)
    state.chmod(0o755)

    check_state_directory(state)


def test_the_directory_above_may_be_group_writable_and_not_world_writable(tmp_path: Path) -> None:
    """A clone makes `.dirigent` under the umask, and some systems default to a group-writable one."""
    state = honest_state(tmp_path)
    state.parent.chmod(0o775)
    check_state_directory(state)

    state.parent.chmod(0o777)
    assert refusal(state) == "database.state_writable"


@pytest.mark.parametrize(
    "init",
    [
        pytest.param((), id="default"),
        pytest.param(("--object-format=sha256",), id="sha256"),
    ],
)
def test_a_committed_state_in_a_fresh_clone_is_refused(tmp_path: Path, init: tuple[str, ...]) -> None:
    """A clone's files are this user's own with ordinary modes, so only the index tells them apart."""
    committed_state(tmp_path / "author", *init)
    git("clone", "-q", str(tmp_path / "author"), str(tmp_path / "checkout"), cwd=tmp_path)

    assert refusal(tmp_path / "checkout" / ".dirigent" / "state") == "database.state_tracked"


@pytest.mark.parametrize("version", ["2", "3", "4"])
def test_every_index_version_is_read(tmp_path: Path, version: str) -> None:
    """Names of every length before the state walk each entry's padding and each shared prefix."""
    state = committed_state(tmp_path)
    for length in range(1, 18):
        (tmp_path / ("!" * length)).write_text("sorted before .dirigent")
    git("add", ".", cwd=tmp_path)
    git("update-index", "--index-version", version, cwd=tmp_path)

    assert refusal(state) == "database.state_tracked"


def test_an_extended_entry_is_read(tmp_path: Path) -> None:
    """Version 3 exists for the extended flags, which lengthen the entries carrying them."""
    state = committed_state(tmp_path)
    (tmp_path / "!first").write_text("sorted before .dirigent")
    git("add", "--intent-to-add", "!first", cwd=tmp_path)

    assert refusal(state) == "database.state_tracked"


def test_a_split_index_is_followed_to_the_shared_one(tmp_path: Path) -> None:
    state = committed_state(tmp_path)
    git("update-index", "--split-index", cwd=tmp_path)

    assert list((tmp_path / ".git").glob("sharedindex.*")), "the index did not split"
    assert refusal(state) == "database.state_tracked"


def test_a_state_tracked_from_a_subdirectory_of_the_repository_is_refused(tmp_path: Path) -> None:
    state = honest_state(tmp_path / "repo" / "sub" / "project")
    git("init", "-q", cwd=tmp_path / "repo")
    git("add", "-f", ".", cwd=tmp_path / "repo")

    assert refusal(state) == "database.state_tracked"


def test_a_worktree_is_read_through_its_git_file(tmp_path: Path) -> None:
    committed_state(tmp_path / "repo")
    git("worktree", "add", "-q", str(tmp_path / "other"), cwd=tmp_path / "repo")

    assert refusal(tmp_path / "other" / ".dirigent" / "state") == "database.state_tracked"


def test_a_state_a_submodule_tracks_is_refused(tmp_path: Path) -> None:
    """The `.dirigent` of a checkout can be a submodule, whose index is the one that names the state."""
    module = tmp_path / "module"
    module.mkdir()
    (module / "state").mkdir()
    (module / "state" / "dirigent.db").write_text("a database")
    git("init", "-q", cwd=module)
    git("add", ".", cwd=module)
    git("commit", "-qm", "state", cwd=module)
    author = tmp_path / "author"
    author.mkdir()
    git("init", "-q", cwd=author)
    git("submodule", "add", "-q", str(module), ".dirigent", cwd=author)
    git("commit", "-qm", "module", cwd=author)
    git("clone", "-q", "--recurse-submodules", str(author), str(tmp_path / "checkout"), cwd=tmp_path)

    assert refusal(tmp_path / "checkout" / ".dirigent" / "state") == "database.state_tracked"


def test_a_different_case_is_the_same_state(tmp_path: Path) -> None:
    """A case-insensitive filesystem opens what the index spells differently."""
    git("init", "-q", cwd=tmp_path)
    tracked = tmp_path / ".DIRIGENT" / "State"
    tracked.mkdir(parents=True)
    (tracked / "dirigent.db").write_text("a database")
    git("add", "-f", ".DIRIGENT", cwd=tmp_path)

    state = tmp_path / ".dirigent" / "state"
    state.mkdir(parents=True, exist_ok=True)

    assert refusal(state) == "database.state_tracked"


def test_state_ignored_beside_tracked_files_is_accepted(tmp_path: Path) -> None:
    """A project commits `.dirigent/profiles.yaml` and ignores the state beside it."""
    state = honest_state(tmp_path)
    (tmp_path / ".dirigent" / "profiles.yaml").write_text("profiles: {}\n")
    (tmp_path / ".dirigent" / ".gitignore").write_text("state/\n")
    (tmp_path / ".dirigent" / "stateful").write_text("a name that only starts like it")
    git("init", "-q", cwd=tmp_path)
    git("add", ".", cwd=tmp_path)
    git("commit", "-qm", "project", cwd=tmp_path)

    check_state_directory(state)


def test_a_repository_with_nothing_added_yet_is_accepted(tmp_path: Path) -> None:
    state = honest_state(tmp_path)
    git("init", "-q", cwd=tmp_path)

    check_state_directory(state)


def test_an_index_that_cannot_be_read_is_not_taken_as_nothing_tracked(tmp_path: Path) -> None:
    state = honest_state(tmp_path)
    git("init", "-q", cwd=tmp_path)
    (tmp_path / ".git" / "index").write_bytes(b"DIRC\x00\x00\x00\x02\x00\x00\x00\x01garbage")

    assert refusal(state) == "database.state_unchecked"


def test_a_repository_s_own_configuration_is_never_run(tmp_path: Path) -> None:
    """What a planted configuration would start is what reading the index by hand avoids."""
    state = committed_state(tmp_path)
    ran = tmp_path / "ran"
    monitor = tmp_path / "monitor.sh"
    monitor.write_text(f"#!/bin/sh\ntouch {ran}\n")
    monitor.chmod(0o755)
    (tmp_path / ".git" / "config").write_text(f"[core]\n\tfsmonitor = {monitor}\n")

    assert refusal(state) == "database.state_tracked"
    assert not ran.exists()


def test_a_database_the_host_named_elsewhere_is_not_checked(tmp_path: Path, victim: Path) -> None:
    (tmp_path / "linked").symlink_to(victim)

    check_state(Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'linked' / 'dirigent.db'}"))


def test_clearing_removes_an_honest_state_and_answers_that_it_did(tmp_path: Path) -> None:
    state = honest_state(tmp_path)

    assert clear_state_directory(state) is True
    assert not state.exists()
    assert clear_state_directory(state) is False, "a state that is not there is not a wipe"


def test_clearing_a_relative_state_takes_the_one_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = honest_state(tmp_path)
    monkeypatch.chdir(tmp_path)

    assert clear_state_directory(Path(".dirigent/state")) is True
    assert not state.exists()


def test_clearing_does_not_delete_through_a_link(tmp_path: Path, victim: Path) -> None:
    project = tmp_path / "project"
    (project / ".dirigent").mkdir(parents=True)
    state = project / ".dirigent" / "state"
    state.symlink_to(victim)

    with pytest.raises(StateRefused) as refused:
        clear_state_directory(state)

    assert refused.value.code == "database.state_is_a_link"
    assert (victim / "dirigent.db").exists()
    assert state.is_symlink(), "the link is left for its owner to look at"


def test_clearing_does_not_delete_through_a_linked_dirigent_directory(tmp_path: Path, victim: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".dirigent").symlink_to(victim.parent)

    with pytest.raises(StateRefused):
        clear_state_directory(project / ".dirigent" / "state")

    assert (victim / "dirigent.db").exists()


def test_clearing_unlinks_a_link_inside_the_state_and_keeps_what_it_points_at(tmp_path: Path, victim: Path) -> None:
    state = honest_state(tmp_path)
    (state / "work").symlink_to(victim)

    assert clear_state_directory(state) is True
    assert not state.exists()
    assert (victim / "dirigent.db").exists()


def test_clearing_takes_a_state_too_open_to_be_opened(tmp_path: Path) -> None:
    """A wipe is the way out of a group-writable state, and what follows it is private."""
    state = honest_state(tmp_path)
    state.chmod(0o775)

    assert clear_state_directory(state) is True


def test_clearing_leaves_a_committed_state_in_place(tmp_path: Path) -> None:
    """Deleting tracked files would rewrite the checkout, and the next start is refused anyway."""
    state = committed_state(tmp_path)

    with pytest.raises(StateRefused) as refused:
        clear_state_directory(state)

    assert refused.value.code == "database.state_tracked"
    assert (state / "dirigent.db").exists()
