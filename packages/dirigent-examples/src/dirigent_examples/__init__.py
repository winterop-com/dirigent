"""The dirigent example corpus, installed: shelves of runnable ``dirigent/v1`` documents."""

from collections.abc import Sequence
from importlib.resources import files
from importlib.resources.abc import Traversable

from dirigent_plugin import extension

#: The directory the topic shelves live in, inside this distribution.
SHELVES_DIRECTORY = "shelves"


class ExamplesPlugin:
    """The plugin object the host discovers under the dirigent.plugins.v1 entry-point group."""

    @extension
    def examples(self) -> Sequence[Traversable]:
        """Contribute the shelves this distribution carries, and nothing else."""
        return [files(__package__ or "dirigent_examples") / SHELVES_DIRECTORY]


plugin = ExamplesPlugin()
