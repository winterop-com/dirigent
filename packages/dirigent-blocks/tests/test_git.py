"""Tests for git.checkout, against a bare repository on disk rather than a network remote."""

import asyncio
import shutil
import subprocess as std_subprocess
from pathlib import Path
from typing import NamedTuple

import pytest
from pydantic import SecretStr, ValidationError

from dirigent_blocks.capture import REDACTED, scrub
from dirigent_blocks.git import (
    GitCheckoutConfig,
    GitCheckoutOperator,
    GitCheckoutOutput,
    GitConnectionConfig,
    GitConnectionKind,
    classify,
    credentials,
    public_url,
)
from dirigent_plugin import BlockFailure, ErrorClass
from dirigent_testing import FakeContext

#: A port nothing listens on, for the remote that cannot be reached.
DEAD_REMOTE = "https://127.0.0.1:1/owner/repo.git"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not on this host's PATH")


class Remote(NamedTuple):
    """A bare repository standing in for a hosting service, and the objects in it."""

    url: str
    first: str
    second: str
    branch: str


def run(directory: Path, *argv: str) -> str:
    """Run one git command in a directory and return what it printed, failing loudly if it did not."""
    done = std_subprocess.run(  # noqa: S603
        ["git", *argv],  # noqa: S607
        cwd=directory,
        capture_output=True,
        check=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(directory), "GIT_TERMINAL_PROMPT": "0"},
    )
    return done.stdout.strip()


def author(directory: Path) -> None:
    """Give the throwaway working copy an identity, so a commit is possible without a real one."""
    run(directory, "config", "user.email", "tests@dirigent.invalid")
    run(directory, "config", "user.name", "dirigent tests")
    run(directory, "config", "commit.gpgsign", "false")


@pytest.fixture
def remote(tmp_path: Path) -> Remote:
    """A bare repository with two commits on its default branch, a tag, and a second branch."""
    bare = tmp_path / "origin.git"
    bare.mkdir()
    run(bare, "init", "--bare", "--initial-branch", "main", "--quiet")
    work = tmp_path / "work"
    work.mkdir()
    run(work, "init", "--initial-branch", "main", "--quiet")
    author(work)
    (work / "README.md").write_text("one\n")
    run(work, "add", "README.md")
    run(work, "commit", "--quiet", "-m", "first")
    first = run(work, "rev-parse", "HEAD")
    run(work, "tag", "v1")
    (work / "README.md").write_text("two\n")
    run(work, "commit", "--quiet", "-am", "second")
    second = run(work, "rev-parse", "HEAD")
    run(work, "checkout", "--quiet", "-b", "feature")
    (work / "feature.txt").write_text("on the branch\n")
    run(work, "add", "feature.txt")
    run(work, "commit", "--quiet", "-m", "third")
    branch = run(work, "rev-parse", "HEAD")
    run(work, "remote", "add", "origin", str(bare))
    run(work, "push", "--quiet", "origin", "main", "feature", "v1")
    return Remote(url=f"file://{bare}", first=first, second=second, branch=branch)


@pytest.fixture
def public(remote: Remote) -> GitConnectionConfig:
    """A connection to that repository with no credential at all."""
    return GitConnectionConfig(url=remote.url)


def tokened(remote: Remote) -> GitConnectionConfig:
    """The bare repository, with a token bolted on for the tests about where a token goes.

    The model refuses a token on a ``file://`` remote, and rightly: a token is HTTP basic auth.
    What is under test is where the credential ends up, which is the same wherever it is bound.
    """
    return GitConnectionConfig.model_construct(
        url=remote.url, username="x-access-token", token=SecretStr("ghp_x"), ssh_key=None, known_hosts=None
    )


#: A remote helper that says something, waits, and only then serves the repository. The wait is
#: what makes a clone long enough to watch, and the word is what a live line carries.
SLOW_HELPER = """#!/bin/sh
echo "the remote says $3" 1>&2
[ -n "$GIT_ASKPASS" ] && echo "the remote saw $(cat "$(dirname "$GIT_ASKPASS")/password")" 1>&2
sleep "$2"
exec git-upload-pack "$1"
"""


def slow_remote(ctx: FakeContext, remote: Remote, word: str, delay: str = "2") -> str:
    """The same bare repository behind that helper, as an ``ext::`` URL git will accept.

    The ``ext`` transport is refused by default, and HOME is the run's scratch space, so the
    allowance goes in the config git reads there.
    """
    root = work_root(ctx)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".gitconfig").write_text('[protocol "ext"]\n\tallow = always\n')
    helper = root / "slow-upload-pack.sh"
    helper.write_text(SLOW_HELPER)
    helper.chmod(0o755)
    return f"ext::{helper} {remote.url.removeprefix('file://')} {delay} {word}"


def logged(ctx: FakeContext, stream: str) -> list[str]:
    """The messages the run log holds for one stream, in order."""
    return [message for _, message, fields in ctx.log.entries if fields.get("stream") == stream]


def install(ctx: FakeContext, connection: GitConnectionConfig) -> FakeContext:
    """Give the fake context the connection a checkout step names."""
    ctx.connections["origin"] = connection
    return ctx


def work_root(ctx: FakeContext) -> Path:
    """The run's work directory, which is where a checkout lands."""
    return ctx.work


def private_directories(ctx: FakeContext) -> list[Path]:
    """The credential directories still sitting in the run's work directory."""
    return list(work_root(ctx).glob("dirigent-git-*"))


async def checkout(
    ctx: FakeContext,
    *,
    ref: str | None = None,
    target: str = "",
    depth: int = 1,
    submodules: bool = False,
) -> GitCheckoutOutput:
    """Run one checkout step and insist it produced an output rather than a handle."""
    config = GitCheckoutConfig(connection="origin", ref=ref, target=target, depth=depth, submodules=submodules)
    output = await GitCheckoutOperator().execute(config, ctx.as_context())
    assert isinstance(output, GitCheckoutOutput)
    return output


# -- the block is ordinary, not unsafe -------------------------------------------


def test_the_block_is_ordinary_and_idempotent() -> None:
    assert GitCheckoutOperator.spec.local_execution is False
    assert GitCheckoutOperator.spec.idempotent is True


# -- the connection kind ---------------------------------------------------------


def test_the_kind_declares_its_id_and_its_config() -> None:
    assert GitConnectionKind.id == "git"
    assert GitConnectionKind.config_model is GitConnectionConfig


def test_the_credential_fields_are_the_ones_a_server_seals() -> None:
    from dirigent_core.secrets import secret_fields

    assert sorted(secret_fields(GitConnectionConfig)) == ["ssh_key", "token"]


def test_a_token_never_renders_itself() -> None:
    config = GitConnectionConfig(url="https://host/o/r.git", token=SecretStr("ghp_notreal"))
    assert "ghp_notreal" not in str(config)
    assert "ghp_notreal" not in repr(config)
    assert config.token is not None
    assert config.token.get_secret_value() == "ghp_notreal"


def test_the_username_defaults_to_what_the_hosts_accept() -> None:
    assert GitConnectionConfig(url="https://host/o/r.git").username == "x-access-token"


def test_two_credentials_at_once_are_refused() -> None:
    with pytest.raises(ValidationError, match="never both"):
        GitConnectionConfig(url="https://host/o/r.git", token=SecretStr("t"), ssh_key=SecretStr("k"))


def test_a_token_on_an_ssh_remote_is_refused() -> None:
    with pytest.raises(ValidationError, match="must be http or https"):
        GitConnectionConfig(url="ssh://git@host/o/r.git", token=SecretStr("t"))


def test_a_key_on_an_https_remote_is_refused() -> None:
    with pytest.raises(ValidationError, match="needs an ssh remote"):
        GitConnectionConfig(url="https://host/o/r.git", ssh_key=SecretStr("k"))


def test_a_key_is_accepted_on_either_ssh_form() -> None:
    assert GitConnectionConfig(url="ssh://git@host/o/r.git", ssh_key=SecretStr("k")).ssh_key is not None
    assert GitConnectionConfig(url="git@host:o/r.git", ssh_key=SecretStr("k")).ssh_key is not None


async def test_a_check_reports_the_branches_it_could_list(public: GitConnectionConfig) -> None:
    report = await GitConnectionKind().check(public)
    assert report.healthy is True
    assert report.detail == "2 branches"


async def test_a_check_of_an_unreachable_remote_is_red() -> None:
    report = await GitConnectionKind().check(GitConnectionConfig(url=DEAD_REMOTE))
    assert report.healthy is False
    assert report.detail


# -- config validators -----------------------------------------------------------


def test_a_target_that_climbs_out_is_refused() -> None:
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        GitCheckoutConfig(connection="origin", target="/etc")
    with pytest.raises(ValidationError, match="cannot be absolute or climb out"):
        GitCheckoutConfig(connection="origin", target="../elsewhere")


def test_a_negative_depth_is_refused() -> None:
    with pytest.raises(ValidationError):
        GitCheckoutConfig(connection="origin", depth=-1)


# -- what lands ------------------------------------------------------------------


async def test_a_checkout_with_no_ref_takes_the_default_branch(
    local_ctx: FakeContext, public: GitConnectionConfig, remote: Remote
) -> None:
    output = await checkout(install(local_ctx, public))

    assert output.commit == remote.second
    assert output.ref == "main"
    assert output.target == local_ctx.step
    assert output.remote == remote.url
    assert (work_root(local_ctx) / local_ctx.step / "README.md").read_text() == "two\n"


async def test_a_checkout_lands_where_the_target_names(local_ctx: FakeContext, public: GitConnectionConfig) -> None:
    output = await checkout(install(local_ctx, public), target="source/project")

    assert output.target == "source/project"
    assert (work_root(local_ctx) / "source/project/README.md").exists()


async def test_a_tag_is_checked_out_by_name(
    local_ctx: FakeContext, public: GitConnectionConfig, remote: Remote
) -> None:
    output = await checkout(install(local_ctx, public), ref="v1")

    assert output.commit == remote.first
    assert output.ref == "v1"
    assert (work_root(local_ctx) / local_ctx.step / "README.md").read_text() == "one\n"


async def test_a_branch_is_checked_out_by_name(
    local_ctx: FakeContext, public: GitConnectionConfig, remote: Remote
) -> None:
    output = await checkout(install(local_ctx, public), ref="feature")

    assert output.commit == remote.branch
    assert (work_root(local_ctx) / local_ctx.step / "feature.txt").exists()


async def test_a_commit_sha_is_fetched_and_detached_onto(
    local_ctx: FakeContext, public: GitConnectionConfig, remote: Remote
) -> None:
    output = await checkout(install(local_ctx, public), ref=remote.first)

    assert output.commit == remote.first
    assert output.ref == remote.first
    assert (work_root(local_ctx) / local_ctx.step / "README.md").read_text() == "one\n"


async def test_a_shallow_checkout_carries_one_commit_and_a_full_one_carries_them_all(
    local_ctx: FakeContext, public: GitConnectionConfig
) -> None:
    await checkout(install(local_ctx, public), target="shallow", depth=1)
    assert run(work_root(local_ctx) / "shallow", "rev-list", "--count", "HEAD") == "1"

    await checkout(local_ctx, target="full", depth=0)
    assert run(work_root(local_ctx) / "full", "rev-list", "--count", "HEAD") == "2"


async def test_submodules_are_checked_out_when_asked(local_ctx: FakeContext, tmp_path: Path, remote: Remote) -> None:
    # A submodule over a file:// URL is refused by default since git 2.38, and HOME is the
    # run's scratch space, so the allowance goes in the config git reads there.
    root = work_root(local_ctx)
    root.mkdir(parents=True, exist_ok=True)
    (root / ".gitconfig").write_text('[protocol "file"]\n\tallow = always\n')
    parent = tmp_path / "parent.git"
    parent.mkdir()
    run(parent, "init", "--bare", "--initial-branch", "main", "--quiet")
    work = tmp_path / "parent-work"
    work.mkdir()
    run(work, "init", "--initial-branch", "main", "--quiet")
    author(work)
    run(work, "-c", "protocol.file.allow=always", "submodule", "add", "--quiet", remote.url, "vendor")
    run(work, "commit", "--quiet", "-m", "with a submodule")
    run(work, "remote", "add", "origin", str(parent))
    run(work, "push", "--quiet", "origin", "main")
    install(local_ctx, GitConnectionConfig(url=f"file://{parent}"))

    await checkout(local_ctx, submodules=True)

    assert (root / local_ctx.step / "vendor" / "README.md").exists()


# -- idempotence -----------------------------------------------------------------


async def test_a_second_run_onto_the_same_commit_leaves_the_checkout_alone(
    local_ctx: FakeContext, public: GitConnectionConfig, remote: Remote
) -> None:
    first = await checkout(install(local_ctx, public))
    marker = work_root(local_ctx) / local_ctx.step / "untouched.txt"
    marker.write_text("still here\n")

    second = await checkout(local_ctx)

    assert second.commit == first.commit == remote.second
    assert second.ref == first.ref == "main", "a no-op re-run reports what a first one would"
    assert marker.read_text() == "still here\n", "a no-op re-run must not clone over the tree"


async def test_a_re_run_at_another_ref_replaces_the_checkout(
    local_ctx: FakeContext, public: GitConnectionConfig, remote: Remote
) -> None:
    await checkout(install(local_ctx, public))
    marker = work_root(local_ctx) / local_ctx.step / "untouched.txt"
    marker.write_text("gone\n")

    output = await checkout(local_ctx, ref="v1")

    assert output.commit == remote.first
    assert not marker.exists()


async def test_a_target_holding_something_that_is_not_a_checkout_is_replaced(
    local_ctx: FakeContext, public: GitConnectionConfig
) -> None:
    stale = work_root(local_ctx) / local_ctx.step
    stale.mkdir(parents=True, exist_ok=True)
    (stale / "leftover.txt").write_text("from an earlier attempt\n")

    await checkout(install(local_ctx, public))

    assert not (stale / "leftover.txt").exists()
    assert (stale / "README.md").exists()


# -- how a checkout fails --------------------------------------------------------


async def test_a_ref_that_does_not_exist_fails_with_gits_own_words(
    local_ctx: FakeContext, public: GitConnectionConfig
) -> None:
    with pytest.raises(BlockFailure) as raised:
        await checkout(install(local_ctx, public), ref="no-such-branch")
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "no-such-branch" in str(raised.value)


async def test_a_remote_that_is_not_there_fails_the_step(local_ctx: FakeContext) -> None:
    install(local_ctx, GitConnectionConfig(url=f"file://{work_root(local_ctx)}/nothing-here.git"))
    with pytest.raises(BlockFailure, match="exited"):
        await checkout(local_ctx)


def test_a_remote_that_could_not_be_reached_is_transient_and_one_that_said_no_is_not() -> None:
    assert classify(b"fatal: Could not resolve host: example.invalid\n") is ErrorClass.TRANSIENT
    assert classify(b"fatal: Authentication failed for 'https://host/o/r.git'\n") is ErrorClass.REJECTED
    assert classify(b"fatal: something nobody has seen before\n") is ErrorClass.UNKNOWN


async def test_a_checkout_lands_in_the_work_directory_whatever_scratch_is(
    local_ctx: FakeContext, public: GitConnectionConfig
) -> None:
    """A checkout is a directory on the worker, so a bucket for an artifact root is no obstacle."""
    local_ctx.scratch_uri = "s3://bucket/artifacts/runs/one"
    output = await checkout(install(local_ctx, public))
    assert (work_root(local_ctx) / output.target / "README.md").exists()


async def test_a_worker_without_git_says_so(
    local_ctx: FakeContext, public: GitConnectionConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing(_name: str, path: str | None = None) -> str | None:
        return None

    monkeypatch.setattr(shutil, "which", missing)
    with pytest.raises(BlockFailure) as raised:
        await checkout(install(local_ctx, public))
    assert raised.value.error_class is ErrorClass.REJECTED
    assert "not on the worker's PATH" in str(raised.value)


# -- the credential ---------------------------------------------------------------


def test_a_public_url_drops_any_credential_written_into_it() -> None:
    assert public_url("https://user:ghp_secret@host/o/r.git") == "https://host/o/r.git"
    assert public_url("https://host/o/r.git") == "https://host/o/r.git"
    assert public_url("git@host:o/r.git") == "git@host:o/r.git"


def test_scrub_replaces_every_secret_it_is_given() -> None:
    assert scrub("token ghp_secret failed", ["ghp_secret"]) == f"token {REDACTED} failed"
    assert scrub("a then ab", ["a", "ab"]) == f"{REDACTED} then {REDACTED}"
    assert scrub("nothing to hide") == "nothing to hide"


def test_a_token_becomes_an_askpass_helper_and_two_unreadable_files(tmp_path: Path) -> None:
    settings = GitConnectionConfig(url="https://host/o/r.git", token=SecretStr("ghp_secret"))

    with credentials(settings, tmp_path) as sealed:
        helper = Path(sealed.environ["GIT_ASKPASS"])
        directory = helper.parent
        assert directory.stat().st_mode & 0o777 == 0o700
        assert helper.stat().st_mode & 0o777 == 0o700
        assert (directory / "password").read_text() == "ghp_secret"
        assert (directory / "password").stat().st_mode & 0o777 == 0o600
        assert (directory / "username").read_text() == "x-access-token"
        assert sealed.environ["GIT_TERMINAL_PROMPT"] == "0"
        assert "ghp_secret" in sealed.secrets
        assert "ghp_secret" not in " ".join(f"{name}={value}" for name, value in sealed.environ.items())

    assert not directory.exists()


def test_a_key_becomes_a_private_file_the_ssh_command_names(tmp_path: Path) -> None:
    settings = GitConnectionConfig(url="ssh://git@host/o/r.git", ssh_key=SecretStr("-----BEGIN KEY-----\nkkk"))

    with credentials(settings, tmp_path) as sealed:
        command = sealed.environ["GIT_SSH_COMMAND"]
        key = next(iter(tmp_path.glob("dirigent-git-*"))) / "id"
        assert key.stat().st_mode & 0o777 == 0o600
        assert key.read_text().startswith("-----BEGIN KEY-----")
        assert str(key) in command
        assert "StrictHostKeyChecking=accept-new" in command
        assert "UserKnownHostsFile" not in command
        assert str(key) in sealed.secrets, "the key's path is scrubbed out of every message too"
        assert scrub(command, sealed.secrets).count(str(key)) == 0

    assert not list(tmp_path.glob("dirigent-git-*"))


def test_known_hosts_pin_the_host_key_when_the_connection_carries_them(tmp_path: Path) -> None:
    settings = GitConnectionConfig(
        url="ssh://git@host/o/r.git",
        ssh_key=SecretStr("kkk"),
        known_hosts="host ssh-ed25519 AAAAC3Nza",
    )

    with credentials(settings, tmp_path) as sealed:
        command = sealed.environ["GIT_SSH_COMMAND"]
        hosts = next(iter(tmp_path.glob("dirigent-git-*"))) / "known_hosts"
        assert hosts.read_text() == "host ssh-ed25519 AAAAC3Nza\n"
        assert "StrictHostKeyChecking=yes" in command
        assert f"UserKnownHostsFile={hosts}" in command


def test_a_connection_with_no_credential_writes_nothing_to_read(tmp_path: Path) -> None:
    with credentials(GitConnectionConfig(url="https://host/o/r.git"), tmp_path) as sealed:
        directory = next(iter(tmp_path.glob("dirigent-git-*")))
        assert list(directory.iterdir()) == []
        assert sealed.secrets == []
        assert "GIT_ASKPASS" not in sealed.environ


async def test_the_checkout_carries_no_credential_and_leaves_none_behind(
    local_ctx: FakeContext, remote: Remote
) -> None:
    install(local_ctx, tokened(remote))

    output = await checkout(local_ctx)

    config = (work_root(local_ctx) / local_ctx.step / ".git" / "config").read_text()
    assert "ghp_x" not in config
    assert "@" not in config
    assert "ghp_x" not in output.remote
    assert private_directories(local_ctx) == []
    logged = " ".join(str(entry) for entry in local_ctx.log.entries)
    assert "ghp_x" not in logged


async def test_the_private_directory_is_gone_after_a_failure(local_ctx: FakeContext, remote: Remote) -> None:
    install(local_ctx, tokened(remote))
    with pytest.raises(BlockFailure) as raised:
        await checkout(local_ctx, ref="no-such-branch")

    assert "ghp_x" not in str(raised.value)
    assert private_directories(local_ctx) == []


# -- what the run log and the artifacts get ---------------------------------------


async def test_a_line_reaches_the_log_while_the_clone_is_still_running(local_ctx: FakeContext, remote: Remote) -> None:
    """A remote that speaks and then waits has its line logged during the wait, not after it."""
    install(local_ctx, GitConnectionConfig(url=slow_remote(local_ctx, remote, "hello")))
    call = asyncio.create_task(checkout(local_ctx))

    try:
        for _ in range(100):
            if "the remote says hello" in logged(local_ctx, "stderr"):
                break
            await asyncio.sleep(0.05)
        assert "the remote says hello" in logged(local_ctx, "stderr"), "the line waited for the clone to finish"
        assert not call.done()
    finally:
        await call


async def test_a_secret_the_remote_prints_back_is_redacted_in_the_live_line(
    local_ctx: FakeContext, remote: Remote
) -> None:
    """A remote that reads the credential out and echoes it reaches the log with it replaced."""
    url = slow_remote(local_ctx, remote, "hello", delay="0")
    install(
        local_ctx,
        GitConnectionConfig.model_construct(
            url=url, username="x-access-token", token=SecretStr("ghp_x"), ssh_key=None, known_hosts=None
        ),
    )

    await checkout(local_ctx)

    assert f"the remote saw {REDACTED}" in logged(local_ctx, "stderr")
    assert "ghp_x" not in " ".join(str(entry) for entry in local_ctx.log.entries)


async def test_the_stream_artifacts_of_a_checkout_carry_no_credential(local_ctx: FakeContext, remote: Remote) -> None:
    """The credential is in a file the askpass helper reads, so git prints it into neither stream."""
    install(local_ctx, tokened(remote))

    output = await checkout(local_ctx)

    for uri in (output.stdout_uri, output.stderr_uri):
        assert b"ghp_x" not in local_ctx.storage.path_for(uri).read_bytes()


async def test_the_output_names_both_streams_and_they_read_back(
    local_ctx: FakeContext, public: GitConnectionConfig
) -> None:
    output = await checkout(install(local_ctx, public))

    assert output.stdout_uri.endswith("attempt-1-clone-stdout.txt")
    assert output.stderr_uri.endswith("attempt-1-clone-stderr.txt")
    assert local_ctx.storage.path_for(output.stdout_uri).exists()
    assert "Cloning into" in local_ctx.storage.path_for(output.stderr_uri).read_text()


async def test_a_commit_sha_names_the_fetch_that_brought_it(
    local_ctx: FakeContext, public: GitConnectionConfig, remote: Remote
) -> None:
    output = await checkout(install(local_ctx, public), ref=remote.first)

    assert output.stderr_uri.endswith("attempt-1-fetch-stderr.txt")
    assert local_ctx.storage.path_for(output.stderr_uri).exists()


async def test_a_checkout_that_was_already_there_names_no_streams(
    local_ctx: FakeContext, public: GitConnectionConfig
) -> None:
    """Nothing was fetched, so there is nothing to point at."""
    await checkout(install(local_ctx, public))

    second = await checkout(local_ctx)

    assert second.stdout_uri == ""
    assert second.stderr_uri == ""


async def test_a_relative_work_root_lands_one_checkout_and_not_two(
    local_ctx: FakeContext, public: GitConnectionConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A relative destination is resolved once by the worker and once more by git, into a doubled path."""
    monkeypatch.chdir(tmp_path)
    local_ctx.work_dir = Path("./state/work/runs/one")

    output = await checkout(install(local_ctx, public))

    root = Path.cwd() / "state/work/runs/one"
    assert (root / output.target / "README.md").exists()
    assert not (root / "state").exists(), "the work root was resolved a second time"
