"""The transform block family: reshaping a value with jq, and trading the text formats."""

from dirigent_block_transform.convert_std import StdConverter
from dirigent_block_transform.transform_jq import JqFilterer, JqMapper, JqTransformer
from dirigent_plugin import Contribution, extension


class TransformBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the jq engines and the codec between json, ndjson, csv, yaml and xml."""
        return Contribution(operators=[JqTransformer(), JqMapper(), JqFilterer(), StdConverter()])


plugin = TransformBlocks()

__all__ = [
    "JqFilterer",
    "JqMapper",
    "JqTransformer",
    "StdConverter",
    "TransformBlocks",
    "plugin",
]
