"""The formatter contract: a name, a version, and one method turning a record into a line.

A formatter is contributed by a package that depends on neither the CLI nor the block
contract, so the protocol every implementation is checked against lives here.
"""

from typing import Protocol, runtime_checkable

from dirigent_common.types import JsonMap


@runtime_checkable
class Formatter(Protocol):
    """One way of turning a record into a line."""

    name: str
    version: str

    def render(self, record: JsonMap) -> object:
        """Render one record: a line, or a line with what the kind puts beneath it.

        What the CLI prints is a string, or anything rich's console renders -- a table, a
        group of both. The type is left open here so that this package names no renderer.
        """
        ...
