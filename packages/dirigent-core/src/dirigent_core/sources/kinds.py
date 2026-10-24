"""The source kinds this instance knows, keyed by the ``kind`` a document writes."""

from dirigent_core.sources.endpoint import EndpointSource
from dirigent_plugin.sources import AnySource, ReceivedSource

#: The kinds dirigent itself provides.
BUILT_IN: tuple[AnySource, ...] = (EndpointSource(),)


def built_in_kinds() -> dict[str, AnySource]:
    """Index the built-in kinds by the ``kind`` a document writes."""
    return {source.spec.kind: source for source in BUILT_IN}


def replies(kind: AnySource | None) -> bool:
    """Say whether a reply node may answer an input of this kind."""
    return kind is not None and kind.spec.replies


def is_received(kind: AnySource | None) -> bool:
    """Say whether the server takes this kind's inputs itself."""
    return isinstance(kind, ReceivedSource)
