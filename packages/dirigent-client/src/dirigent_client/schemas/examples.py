"""Examples: the documents every installed plugin ships, and the starters among them."""

from pydantic import Field

from dirigent_client.schemas.common import WireModel
from dirigent_client.schemas.pipelines import Requirements


class ExampleOut(WireModel):
    """One document of the installed corpus, as a listing shows it."""

    code: str
    name: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list[str])
    requires: Requirements = Field(default_factory=Requirements)
    """What the instance must already hold before this document can be applied."""

    plugin: str
    """The distribution the shelves came from, named as the plugin host names a contributor."""

    shelf: str
    """The directory the file sits in, relative to the shelves root; empty at the root."""

    starter: bool = False
    """Whether this document opted in to being copied into a project as a starting point."""

    carries: list[str] = Field(default_factory=list[str])
    """The top-level sections this document carries rather than requires, which an instance
    refuses to store: ``connections``, ``schemas``."""


class ExampleDetail(ExampleOut):
    """One example plus the text a copy of it copies."""

    source: str
    """The document's text, verbatim."""

    path: str
    """The file, relative to the shelves root."""
