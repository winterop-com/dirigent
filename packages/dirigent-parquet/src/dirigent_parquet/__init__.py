"""The parquet format pack: the ``convert.arrow`` codec, on pyarrow."""

from dirigent_parquet.arrow import BYTES_BY_URI, TEXT_FORMATS, UNIT, ArrowConverter
from dirigent_plugin import Contribution, extension


class ParquetPlugin:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the ``convert.arrow`` codec."""
        return Contribution(operators=[ArrowConverter()])


plugin = ParquetPlugin()

__all__ = [
    "BYTES_BY_URI",
    "TEXT_FORMATS",
    "UNIT",
    "ArrowConverter",
    "ParquetPlugin",
    "plugin",
]
