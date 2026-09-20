"""The jq engine for the transform verbs: reshaping a value, and the element-wise pair."""

from dirigent_block_transform_jq.transform_jq import JqFilterer, JqMapper, JqTransformer
from dirigent_plugin import Contribution, extension


class TransformJqBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the jq engines behind the transform, map and filter verbs."""
        return Contribution(operators=[JqTransformer(), JqMapper(), JqFilterer()])


plugin = TransformJqBlocks()

__all__ = [
    "JqFilterer",
    "JqMapper",
    "JqTransformer",
    "TransformJqBlocks",
    "plugin",
]
