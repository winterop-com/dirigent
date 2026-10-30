"""The source kinds this instance knows, keyed by the ``kind`` a document writes."""

from collections.abc import Mapping

from dirigent_core.sources.endpoint import EndpointSource
from dirigent_core.sources.sensor import AnySensor, SensorSource
from dirigent_core.sources.storage import StorageSource
from dirigent_plugin.sources import AnySource, ReceivedSource


def built_in(sensors: Mapping[str, AnySensor] | None = None) -> tuple[AnySource, ...]:
    """The kinds dirigent itself provides, the sensor kind poking the sensors given."""
    return (EndpointSource(), StorageSource(), SensorSource(sensors))


def built_in_kinds() -> dict[str, AnySource]:
    """Index the built-in kinds by the ``kind`` a document writes, for a check that has no host."""
    return {source.spec.kind: source for source in built_in()}


def replies(kind: AnySource | None) -> bool:
    """Say whether a reply node may answer an input of this kind."""
    return kind is not None and kind.spec.replies


def is_received(kind: AnySource | None) -> bool:
    """Say whether the server takes this kind's inputs itself."""
    return isinstance(kind, ReceivedSource)
