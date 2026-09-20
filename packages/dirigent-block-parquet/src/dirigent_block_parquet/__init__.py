"""The parquet block family: the ``convert.arrow`` codec, on pyarrow."""

from dirigent_block_parquet.arrow import TEXT_FORMATS, UNIT, ArrowConverter
from dirigent_plugin import Contribution, extension


class ParquetBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the ``convert.arrow`` codec."""
        return Contribution(operators=[ArrowConverter()])


plugin = ParquetBlocks()

__all__ = [
    "TEXT_FORMATS",
    "UNIT",
    "ArrowConverter",
    "ParquetBlocks",
    "plugin",
]
