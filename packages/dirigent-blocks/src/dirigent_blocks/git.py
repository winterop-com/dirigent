"""``git.checkout``: put a repository at a ref into the run's work directory.

Nothing else can bring an existing project into a run. ``storage.copy`` moves one object at a
time, the compose and build blocks read only what is already in the work directory, and
``shell.run`` with a ``git clone`` is an unsafe block on a worker that happens to have git and
a network. This block clones into a directory under the run's work directory and reports the
commit it landed on, so a downstream ``docker.compose.up`` names its compose file, a
``docker.build`` names its context, and a transform names its files, all relative to that
directory.

It is an **ordinary** block. It writes only under the run's work directory and reaches only the
remote its connection names, which is a narrower grant than ``shell.run`` and does not need the
unsafe allowlist. A checkout is a directory a tool opens, so it lands on the worker's own
filesystem rather than in storage, and a step that reads it runs on the same worker.

The credential never becomes an argument. A token reaches git through a ``GIT_ASKPASS`` helper
that reads it out of a file in a 0700 directory of its own; an ssh key is a 0600 file that
``GIT_SSH_COMMAND`` names. The remote is always given to git with any userinfo stripped, so the
checkout's ``.git/config`` holds no credential either, and the directory holding both goes away
when the step leaves however it leaves.
"""

import contextlib
import re
import shutil
import tempfile
from collections.abc import Generator
from datetime import timedelta
from pathlib import Path
from typing import ClassVar
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, SecretStr, model_validator

from dirigent_blocks import secrets, subprocess
from dirigent_blocks.capture import log_stream, scrub, tail
from dirigent_common import BlockModel, Duration, HealthReport
from dirigent_plugin import (
    BlockFailure,
    ConnectionKind,
    ConnectionRef,
    ErrorClass,
    Operator,
    OperatorSpec,
    RemoteHandle,
    StepContext,
)

#: How long a connection check may spend listing a remote's refs.
CHECK_TIMEOUT_SECONDS = 30.0

#: A ref written as a full object name, which no clone can resolve by ``--branch``.
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")

#: A remote that can carry a token: the credential is HTTP basic auth underneath.
HTTP_SCHEMES = ("http", "https")

#: A remote that can carry a key, either ``ssh://host/path`` or the scp-like ``user@host:path``.
SSH_SCHEME = "ssh"

#: What git says when the remote, rather than the request, is the problem.
UNREACHABLE = (
    "could not resolve host",
    "connection refused",
    "connection timed out",
    "operation timed out",
    "early eof",
    "the remote end hung up",
    "temporary failure in name resolution",
)

#: What git says when the request was understood and refused, or asked for something absent.
REFUSED = (
    "authentication failed",
    "permission denied",
    "invalid username or password",
    "could not read username",
    "terminal prompts disabled",
    "repository not found",
    "remote branch",
    "did not match any file",
    "couldn't find remote ref",
    "not our ref",
    "access denied",
)

#: The askpass helper git runs. It is asked for a username first and a password second, and
#: answers each out of a file beside it so neither ever reaches an argument list or an
#: environment variable.
ASKPASS = """#!/bin/sh
case "$1" in
Username*) exec cat "{directory}/username" ;;
*) exec cat "{directory}/password" ;;
esac
"""


class GitConnectionConfig(BlockModel):
    """One remote repository and the credential, if any, that reaches it."""

    url: str = Field(min_length=1)
    """The remote, in https form (``https://host/owner/repo.git``) or ssh form
    (``ssh://git@host/owner/repo.git``, or the scp-like ``git@host:owner/repo.git``).

    Any userinfo written into it is stripped before git is given it, so a credential belongs
    in ``token`` or ``ssh_key`` rather than in the URL."""

    username: str = "x-access-token"
    """The user half of the token credential. GitHub and GitLab both accept this literal for a
    personal or deploy token, so a connection that has only a token needs nothing else."""

    token: SecretStr | None = None
    """A personal, deploy or app token, presented as the password half of HTTP basic auth.

    Sealed like every other connection secret: encrypted at rest, redacted in every API
    response, and reaching git only through a file the askpass helper reads."""

    ssh_key: SecretStr | None = None
    """A private key in OpenSSH form, for an ssh remote.

    Written to a 0600 file for the length of one step and removed afterwards. A key with a
    passphrase cannot be used: nothing here can answer the prompt."""

    known_hosts: str | None = None
    """``known_hosts`` lines pinning the host's key, one per line, as ``ssh-keyscan`` prints them.

    Given, the host key must match one of them. Left unset, the first key seen is accepted
    (``StrictHostKeyChecking=accept-new``), which trusts the first connection."""

    @model_validator(mode="after")
    def _check_shape(self) -> "GitConnectionConfig":
        """Refuse two credentials at once, and a credential that does not fit the remote's form."""
        if self.token is not None and self.ssh_key is not None:
            raise ValueError(
                "a git connection carries one credential: a token for an https remote or an "
                "ssh_key for an ssh one, never both"
            )
        scheme = urlsplit(self.url).scheme
        if self.token is not None and scheme not in HTTP_SCHEMES:
            raise ValueError(f"a token is HTTP basic auth, so the url must be http or https, not {self.url!r}")
        if self.ssh_key is not None and not _is_ssh(self.url):
            raise ValueError(f"an ssh_key needs an ssh remote, and {self.url!r} is not one")
        return self


class GitConnectionKind(ConnectionKind):
    """The connection kind ``git.checkout`` resolves its remote and credential through."""

    id: ClassVar[str] = "git"
    config_model: ClassVar[type[BaseModel]] = GitConnectionConfig

    async def check(self, config: BaseModel) -> HealthReport:
        """List the remote's refs, which is the smallest thing that proves reach and credential."""
        settings = GitConnectionConfig.model_validate(config.model_dump())
        binary = shutil.which("git")
        if binary is None:
            return HealthReport(healthy=False, detail="git is not on this host's PATH")
        with tempfile.TemporaryDirectory(prefix="dirigent-git-check-") as home:
            root = Path(home)
            with credentials(settings, root) as sealed:
                environ = {**subprocess.environment([], {}, root), **sealed.environ}
                try:
                    code, out, err = await subprocess.output(
                        argv=[binary, "ls-remote", "--heads", "--", public_url(settings.url)],
                        directory=root,
                        environ=environ,
                        timeout_seconds=CHECK_TIMEOUT_SECONDS,
                        what="git ls-remote",
                    )
                except BlockFailure as error:
                    return HealthReport(healthy=False, detail=scrub(str(error), sealed.secrets))
                if code != 0:
                    detail = _first_line(err) or f"git exited {code}"
                    return HealthReport(healthy=False, detail=scrub(detail, sealed.secrets))
                return HealthReport(healthy=True, detail=f"{len(_first_lines(out))} branches")


class GitCheckoutConfig(BlockModel):
    """Which repository to put where, at what ref, and how much of its history."""

    connection: ConnectionRef
    """The ``git`` connection naming the remote and holding its credential."""

    ref: str | None = None
    """The branch, tag or full commit sha to land on. Unset takes the remote's default branch."""

    target: str = ""
    """The directory the checkout lands in, inside the run's work directory; never absolute,
    never climbing out. Empty takes the step's own name, so a step named ``checkout`` writes
    ``checkout/`` and a downstream ``docker.build`` names ``checkout`` as its context."""

    depth: int = Field(default=1, ge=0)
    """How many commits of history to fetch. ``1`` is a shallow checkout of the ref alone,
    which is what a build wants; ``0`` fetches the whole history, which a step reading the log
    or describing a tag needs."""

    submodules: bool = False
    """Also check out the repository's submodules, recursively."""

    timeout: Duration = timedelta(minutes=10)
    """The deadline on each git invocation, after which it is killed as transient."""

    @model_validator(mode="after")
    def _check_shape(self) -> "GitCheckoutConfig":
        """Refuse a target that is absolute or climbs out of the run's work directory."""
        if self.target and (Path(self.target).is_absolute() or ".." in Path(self.target).parts):
            raise ValueError(
                "a checkout target is a path inside the run's work directory, so it cannot be absolute or climb out"
            )
        return self


class GitCheckoutOutput(BlockModel):
    """Where the working tree is and what is in it, for the steps that read it."""

    commit: str
    """The full sha the checkout landed on, which is the only exact name for what was built."""

    ref: str
    """The ref that was asked for, or the default branch the clone landed on when none was."""

    target: str
    """The checkout's directory, relative to the run's work directory, as a downstream block names it."""

    remote: str
    """The remote it came from, with any credential stripped."""

    stdout_uri: str = ""
    """Where the whole of the fetching command's stdout was written; empty when the checkout was
    already standing and nothing was fetched."""

    stderr_uri: str = ""
    """Where the whole of the fetching command's stderr was written, which is where git prints
    what it is doing; empty when the checkout was already standing and nothing was fetched."""


class GitCheckoutOperator(Operator[GitCheckoutConfig, GitCheckoutOutput]):
    """Clones a repository at a ref into the run's work directory and reports the commit."""

    spec = OperatorSpec(
        id="git.checkout",
        summary="Check a repository out into the run's work directory.",
        idempotent=True,
    )
    config_model: ClassVar[type[BaseModel]] = GitCheckoutConfig
    output_model: ClassVar[type[BaseModel]] = GitCheckoutOutput

    async def execute(self, config: GitCheckoutConfig, ctx: StepContext) -> GitCheckoutOutput | RemoteHandle:
        """Resolve the connection, land the working tree, and report what is in it."""
        root = subprocess.local_root(ctx)
        settings = ctx.connection(config.connection, GitConnectionConfig)
        target = config.target or ctx.step
        destination = root / target
        remote = public_url(settings.url)
        binary = shutil.which("git", path=subprocess.environment([], {}, root).get("PATH"))
        if binary is None:
            raise BlockFailure(
                "git is not on the worker's PATH, so nothing here can check a repository out; "
                "the worker image installs it, a bare host may not",
                error_class=ErrorClass.REJECTED,
            )

        with credentials(settings, root) as sealed:
            environ = {**subprocess.environment([], {}, root), **sealed.environ}
            git = _Git(binary, environ, config.timeout.total_seconds(), sealed.secrets, ctx)
            standing = await _standing(git, config, destination, remote)
            if not standing:
                _clear(destination)
                await _land(git, config, destination, remote)
            commit = await git.read(destination, "rev-parse", "HEAD")
            landed = config.ref or await git.read(destination, "rev-parse", "--abbrev-ref", "HEAD")

        message = "checkout already there" if standing else "checked out"
        ctx.log.info(message, commit=commit, ref=landed, target=target, remote=remote)
        return GitCheckoutOutput(
            commit=commit,
            ref=landed,
            target=target,
            remote=remote,
            stdout_uri=git.stdout_uri,
            stderr_uri=git.stderr_uri,
        )


class Sealed:
    """What one step's credential became: an environment for git, and the strings to scrub."""

    def __init__(self, environ: dict[str, str], secrets: list[str]) -> None:
        """Hold the variables git is given and the values that must never be logged."""
        self.environ = environ
        self.secrets = secrets


@contextlib.contextmanager
def credentials(settings: GitConnectionConfig, parent: Path) -> Generator[Sealed]:
    """Materialise the connection's credential into a private directory, and take it away again.

    The directory is 0700 and holds a 0700 askpass helper and its two 0600 answers, or a 0600
    private key and the host keys to check against. Nothing in it outlives the step: the
    directory goes whether the checkout succeeded, failed, or was cancelled.
    """
    with secrets.private_directory(parent, "dirigent-git-") as directory:
        yield _materialise(settings, directory)


def _materialise(settings: GitConnectionConfig, directory: Path) -> Sealed:
    """Write the credential's files and name the environment that points git at them."""
    # git never asks a terminal for anything: there is none, and a prompt would hang the step
    # until its deadline instead of failing it with what went wrong.
    environ = {"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
    hidden: list[str] = []
    if settings.token is not None:
        token = settings.token.get_secret_value()
        secrets.write(directory / "username", settings.username)
        secrets.write(directory / "password", token)
        helper = directory / "askpass.sh"
        secrets.write(helper, ASKPASS.format(directory=directory), secrets.EXECUTABLE)
        environ["GIT_ASKPASS"] = str(helper)
        hidden.append(token)
    if settings.ssh_key is not None:
        key = directory / "id"
        secrets.write(key, settings.ssh_key.get_secret_value().rstrip("\n") + "\n")
        options = ["-i", str(key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes"]
        if settings.known_hosts is not None:
            hosts = directory / "known_hosts"
            secrets.write(hosts, settings.known_hosts.rstrip("\n") + "\n")
            options += ["-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={hosts}"]
        else:
            options += ["-o", "StrictHostKeyChecking=accept-new"]
        environ["GIT_SSH_COMMAND"] = " ".join(["ssh", *(_quote(one) for one in options)])
        hidden += [settings.ssh_key.get_secret_value(), str(key)]
    return Sealed(environ, hidden)


class _Git:
    """One repository's git, with the binary, the environment and the redaction already bound."""

    def __init__(
        self, binary: str, environ: dict[str, str], timeout: float, secrets: list[str], ctx: StepContext
    ) -> None:
        """Hold what every invocation of this step's git shares."""
        self.binary = binary
        self.environ = environ
        self.timeout = timeout
        self.secrets = secrets
        self.ctx = ctx
        self.stdout_uri = ""
        self.stderr_uri = ""

    async def call(self, directory: Path, *argv: str) -> tuple[int, bytes, bytes]:
        """Run one git command in a directory and hand back its exit code and both streams."""
        code, out, err = await subprocess.output(
            argv=[self.binary, *argv],
            directory=directory,
            environ=self.environ,
            timeout_seconds=self.timeout,
            what=f"git {argv[0]}",
        )
        for line in _first_lines(err):
            self.ctx.log.debug(scrub(line, self.secrets), stream="stderr")
        return code, out, err

    async def run(self, directory: Path, *argv: str) -> bytes:
        """Run one git command that must succeed, failing the step with git's own words if it does not."""
        code, out, err = await self.call(directory, *argv)
        if code != 0:
            detail = tail(err, redact=self.secrets) or tail(out, redact=self.secrets) or "no output"
            raise BlockFailure(f"git {argv[0]} exited {code}: {detail}", error_class=classify(err))
        return out

    async def read(self, directory: Path, *argv: str) -> str:
        """Run one git command that prints a single value, and return that value."""
        return (await self.run(directory, *argv)).decode("utf-8", errors="replace").strip()

    async def stream(self, directory: Path, *argv: str) -> None:
        """Run one git command that talks to the remote, draining both streams to storage as it prints.

        A clone of a large repository prints for minutes, so its lines reach the run log where
        they happen rather than when the process exits, and the whole of each stream is an
        artifact rather than a buffer in the worker. Each command writes its own pair, named for
        its subcommand; the pair the last one wrote is what the output carries.
        """
        artifacts = f"{subprocess.prefix(self.ctx, 'git')}-{argv[0]}"
        stdout_uri = f"{artifacts}-stdout.txt"
        stderr_uri = f"{artifacts}-stderr.txt"
        code, out, err = await subprocess.run(
            directory=directory,
            ctx=self.ctx,
            stdout_uri=stdout_uri,
            stderr_uri=stderr_uri,
            timeout_seconds=self.timeout,
            environ=self.environ,
            argv=[self.binary, *argv],
            what=f"git {argv[0]}",
            redact=self.secrets,
        )
        self.stdout_uri = stdout_uri
        self.stderr_uri = stderr_uri
        log_stream(self.ctx, "stdout", out, self.secrets)
        log_stream(self.ctx, "stderr", err, self.secrets)
        if code != 0:
            detail = tail(err.tail, redact=self.secrets) or tail(out.tail, redact=self.secrets) or "no output"
            raise BlockFailure(f"git {argv[0]} exited {code}: {detail}", error_class=classify(err.tail))


async def _standing(git: _Git, config: GitCheckoutConfig, destination: Path, remote: str) -> bool:
    """Whether the target already holds a working tree at the commit being asked for.

    A retry of a step, or a second run into a work directory that already holds the checkout,
    should cost one ref listing rather than a second clone. Anything that is not a working
    tree at the wanted commit answers false, and the target is then rebuilt from scratch.
    """
    if not (destination / ".git").exists():
        return False
    code, out, _err = await git.call(destination, "rev-parse", "HEAD")
    if code != 0:
        return False
    head = out.decode("utf-8", errors="replace").strip()
    if config.ref is not None and COMMIT_SHA.match(config.ref):
        return head == config.ref
    code, out, _err = await git.call(destination, "ls-remote", "--", remote, config.ref or "HEAD")
    if code != 0:
        return False
    lines = _first_lines(out)
    wanted = lines[0].split("\t", 1)[0] if lines else ""
    return bool(wanted) and head == wanted


async def _land(git: _Git, config: GitCheckoutConfig, destination: Path, remote: str) -> None:
    """Put the working tree at the ref, by whichever of git's two routes reaches it.

    A branch or tag is what ``clone --branch`` takes. A commit sha is not: the ref namespace
    has no entry for it, so the repository is created empty, the one commit is fetched into
    ``FETCH_HEAD``, and the working tree is detached onto that.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if config.ref is not None and COMMIT_SHA.match(config.ref):
        destination.mkdir(parents=True, exist_ok=True)
        await git.run(destination, "init", "--quiet")
        await git.run(destination, "remote", "add", "origin", "--", remote)
        await git.stream(destination, "fetch", *_depth(config), "origin", config.ref)
        await git.run(destination, "checkout", "--quiet", "--detach", "FETCH_HEAD")
        if config.submodules:
            await git.stream(destination, "submodule", "update", "--init", "--recursive", *_depth(config))
        return
    argv = ["clone", *_depth(config)]
    if config.ref is not None:
        argv += ["--branch", config.ref]
    if config.submodules:
        argv += ["--recurse-submodules"]
    await git.stream(destination.parent, *argv, "--", remote, str(destination))


def _depth(config: GitCheckoutConfig) -> list[str]:
    """``--depth`` when the checkout is shallow, and nothing at all when it is not."""
    return ["--depth", str(config.depth)] if config.depth > 0 else []


def public_url(url: str) -> str:
    """The remote with any userinfo removed, which is what git and the output are both given.

    A URL that carries its own credential would put it in the checkout's ``.git/config``,
    where it outlives the step and reaches every later reader of the work directory.
    """
    split = urlsplit(url)
    if not split.scheme or "@" not in split.netloc:
        return url
    return urlunsplit(split._replace(netloc=split.netloc.rsplit("@", 1)[1]))


def _is_ssh(url: str) -> bool:
    """Whether the remote is an ssh one, in either the URL form or the scp-like one."""
    split = urlsplit(url)
    return split.scheme == SSH_SCHEME or (not split.scheme and "@" in url and ":" in url)


def classify(stderr: bytes) -> ErrorClass:
    """A remote that could not be reached is transient; one that said no is not."""
    text = stderr.decode("utf-8", errors="replace").lower()
    if any(marker in text for marker in UNREACHABLE):
        return ErrorClass.TRANSIENT
    if any(marker in text for marker in REFUSED):
        return ErrorClass.REJECTED
    return ErrorClass.UNKNOWN


def _clear(destination: Path) -> None:
    """Empty the target so a clone into it starts from nothing, whatever was there before."""
    if destination.is_symlink() or destination.is_file():
        destination.unlink()
    elif destination.is_dir():
        shutil.rmtree(destination)


def _quote(value: str) -> str:
    """Quote one ssh option for the command line git splits ``GIT_SSH_COMMAND`` into."""
    return value if re.fullmatch(r"[\w@%+=:,./-]+", value) else "'" + value.replace("'", "'\\''") + "'"


def _first_line(payload: bytes) -> str:
    """The first non-blank line of a stream, which is the sentence a health report wants."""
    lines = _first_lines(payload)
    return lines[0] if lines else ""


def _first_lines(payload: bytes) -> list[str]:
    """Every non-blank line of a captured stream."""
    return [line for line in payload.decode("utf-8", errors="replace").splitlines() if line.strip()]
