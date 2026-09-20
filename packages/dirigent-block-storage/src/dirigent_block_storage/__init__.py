"""The storage block family: moving objects between URIs, and waiting for one to appear."""

from dirigent_block_storage.storage import (
    StorageCopyOperator,
    StorageExistsSensor,
    StorageReadOperator,
    StorageWriteOperator,
)
from dirigent_plugin import Contribution, extension


class StorageBlocks:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def contribute(self) -> Contribution:
        """Contribute the storage blocks, which speak every registered URI scheme."""
        return Contribution(
            operators=[StorageCopyOperator(), StorageReadOperator(), StorageWriteOperator()],
            sensors=[StorageExistsSensor()],
        )


plugin = StorageBlocks()

__all__ = [
    "StorageBlocks",
    "StorageCopyOperator",
    "StorageExistsSensor",
    "StorageReadOperator",
    "StorageWriteOperator",
    "plugin",
]
