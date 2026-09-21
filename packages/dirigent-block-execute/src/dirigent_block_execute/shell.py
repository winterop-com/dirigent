"""``shell.run``: the one built-in block that executes code on the worker.

It declares ``local_execution``, which means the engine refuses to run it at all unless the
instance config allowlists its id. That gate exists because "can edit pipelines" must never
silently mean "can run code on workers".
"""

from datetime import timedelta
from pathlib import Path
from typing import Annotated, ClassVar

from pydantic import BaseModel, Field, model_validator

from dirigent_block_execute import subprocess
from dirigent_block_execute.capture import log_stream, tail
from dirigent_block_execute.environment import reject_reserved
from dirigent_block_execute.messages import (
    COMMAND_EXITED,
    CWD_STAYS_INSIDE,
    SHELL_ONE_FORM,
)
from dirigent_common import BlockModel, Duration
from dirigent_plugin import (
    BlockFailure,
    ErrorClass,
    Operator,
    OperatorSpec,
    RemoteHandle,
    ShellString,
    ShellVariables,
    StepContext,
)


class ShellRunConfig(ShellVariables):
    """What to run, where, with what environment, and for how long."""

    argv: list[str] = Field(default_factory=list[str])
    """The command as an argument vector, which does not involve a shell."""

    command: Annotated[str | None, ShellString()] = None
    """The command as a shell string, for when a pipe or a redirect is the point.

    Every ``${...}`` in it is rewritten by the engine to a variable it sets in this command's
    environment, so a value that came from a webhook payload is one word the shell never
    parses, however the reference was quoted -- and inside single quotes, which a shell keeps
    literal, the command reads that variable's name rather than its value. Prefer ``argv``
    anyway: it involves no shell at all."""

    cwd: str | None = None
    """A directory relative to the run's work directory; never an absolute path."""

    env: dict[str, str] = Field(default_factory=dict[str, str])
    """Variables set explicitly for this command."""

    env_allowlist: list[str] = Field(default_factory=list[str])
    """Worker environment variables this command is allowed to inherit.

    Never the instance's own ``DIRIGENT_*`` variables: those hold this instance's secrets,
    and a step that could inherit them could print the envelope key into the run log."""

    timeout: Duration = Field(default=timedelta(minutes=5), gt=timedelta(0))
    """How long the process may run before it is killed as a transient failure."""

    @model_validator(mode="after")
    def _require_one_form(self) -> "ShellRunConfig":
        """Reject a config that names both forms of the command, or neither."""
        if bool(self.argv) == bool(self.command):
            raise ValueError(SHELL_ONE_FORM.render())
        if self.cwd and (Path(self.cwd).is_absolute() or ".." in Path(self.cwd).parts):
            raise ValueError(CWD_STAYS_INSIDE.render())
        reject_reserved(self.env_allowlist)
        return self


class ShellRunOutput(BlockModel):
    """What the command did, with its full streams addressable as artifacts."""

    exit_code: int

    stdout: str
    """The head of what the command printed, cut at the instance's inline capture size.

    Verbatim, including the trailing newline a command like ``echo`` ends with. Use
    ``printf '%s'`` where the value is read by another step."""

    stderr: str
    """The head of what the command printed to stderr, cut the same way."""

    stdout_uri: str
    """Where the whole of stdout was written; never truncated, whatever the field above holds."""

    stderr_uri: str
    """Where the whole of stderr was written; never truncated either."""

    stdout_bytes: int
    """How much the command printed to stdout altogether, inlined or not."""

    stderr_bytes: int
    """How much it printed to stderr altogether."""

    stdout_truncated: bool
    """Whether ``stdout`` above is short of the stream. Only the inline copy is ever cut."""

    stderr_truncated: bool
    """Whether ``stderr`` above is short of the stream, which is an independent question."""


def _environment(config: ShellRunConfig, home: Path) -> dict[str, str]:
    """Build the command's environment, the substituted values last.

    They are set after ``env`` so a document cannot override what a reference resolved to,
    and they are set whatever the allowlist holds: the command reads them because the engine
    put them in it.
    """
    environ = subprocess.environment(config.env_allowlist, config.env, home)
    environ.update(config.shell_variables)
    return environ


class ShellRunOperator(Operator[ShellRunConfig, ShellRunOutput]):
    """Runs a command on the worker, inside the run's work directory and behind the allowlist."""

    spec = OperatorSpec(
        id="shell.run",
        group="execute",
        summary="Run a command on the worker.",
        idempotent=False,
        local_execution=True,
    )
    config_model: ClassVar[type[BaseModel]] = ShellRunConfig
    output_model: ClassVar[type[BaseModel]] = ShellRunOutput

    async def execute(self, config: ShellRunConfig, ctx: StepContext) -> ShellRunOutput | RemoteHandle:
        """Run the command once, capture both streams, and classify how it ended."""
        workspace = subprocess.workspace(ctx, "shell")
        directory = workspace / config.cwd if config.cwd else workspace
        directory.mkdir(parents=True, exist_ok=True)
        code, out, err, stdout_uri, stderr_uri = await subprocess.run(
            directory=directory,
            ctx=ctx,
            timeout_seconds=config.timeout.total_seconds(),
            environ=_environment(config, directory),
            argv=config.argv or None,
            command=config.command,
        )
        log_stream(ctx, "stdout", out)
        log_stream(ctx, "stderr", err)
        ctx.log.info("command finished", exit_code=code, stdout_bytes=out.total_bytes, stderr_bytes=err.total_bytes)
        if code != 0:
            raise BlockFailure(
                COMMAND_EXITED,
                error_class=ErrorClass.UNKNOWN,
                code=code,
                detail=tail(err.tail) or tail(out.tail) or "no output",
            )
        printed = out.captured(ctx.inline_capture)
        failed = err.captured(ctx.inline_capture)
        return ShellRunOutput(
            exit_code=code,
            stdout=printed.text,
            stderr=failed.text,
            stdout_uri=stdout_uri,
            stderr_uri=stderr_uri,
            stdout_bytes=printed.total_bytes,
            stderr_bytes=failed.total_bytes,
            stdout_truncated=printed.truncated,
            stderr_truncated=failed.truncated,
        )
