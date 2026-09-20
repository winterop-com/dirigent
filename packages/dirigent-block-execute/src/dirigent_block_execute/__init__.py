"""The execute block family: what runs code on the worker, in a shell, a container, or a checkout."""

from dirigent_block_execute.build import DockerBuildOperator
from dirigent_block_execute.compose import DockerComposeDownOperator, DockerComposeUpOperator
from dirigent_block_execute.docker import DockerConnectionKind, DockerRunOperator
from dirigent_block_execute.git import GitCheckoutOperator, GitConnectionKind
from dirigent_block_execute.shell import ShellRunOperator
from dirigent_plugin import Contribution, extension


class ExecuteBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the blocks that run something on the worker, and their connection kinds."""
        return Contribution(
            operators=[
                ShellRunOperator(),
                DockerRunOperator(),
                DockerComposeUpOperator(),
                DockerComposeDownOperator(),
                DockerBuildOperator(),
                GitCheckoutOperator(),
            ],
            connection_kinds=[DockerConnectionKind(), GitConnectionKind()],
        )


plugin = ExecuteBlocks()

__all__ = [
    "DockerBuildOperator",
    "DockerComposeDownOperator",
    "DockerComposeUpOperator",
    "DockerConnectionKind",
    "DockerRunOperator",
    "ExecuteBlocks",
    "GitCheckoutOperator",
    "GitConnectionKind",
    "ShellRunOperator",
    "plugin",
]
