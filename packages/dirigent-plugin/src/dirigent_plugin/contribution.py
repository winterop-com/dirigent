"""What one plugin contributes, across every surface, and how the host merges them."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from dirigent_common import API_VERSION, Catalogue
from dirigent_plugin.blocks import (
    AnyOperator,
    AnySensor,
    ConnectionKind,
    FormatCheck,
    Notifier,
    StorageBackend,
    mark_refusal,
)
from dirigent_plugin.messages import DUPLICATE_ID, SOURCE_NOT_HOSTED, UNSUPPORTED_API_VERSION
from dirigent_plugin.sources import AnySource, PolledSource, ReceivedSource, SourceHosting


class Contribution(BaseModel):
    """Everything one plugin adds, across all eight surfaces, gathered by the host at startup."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    api_version: int = Field(default=API_VERSION, ge=1)
    operators: list[AnyOperator] = Field(default_factory=list[AnyOperator])
    sensors: list[AnySensor] = Field(default_factory=list[AnySensor])
    storage_backends: list[StorageBackend] = Field(default_factory=list[StorageBackend])
    notifiers: list[Notifier] = Field(default_factory=list[Notifier])
    connection_kinds: list[ConnectionKind] = Field(default_factory=list[ConnectionKind])
    sources: list[AnySource] = Field(default_factory=list[AnySource])
    """The source kinds this plugin adds, each keyed by the ``kind`` a document writes under ``source``."""

    formats: dict[str, FormatCheck] = Field(default_factory=dict[str, FormatCheck])
    """JSON Schema format checkers this plugin adds, by format name. A schema that writes
    ``format: <name>`` then asserts wherever the contributing pack is installed, and stays a
    passing annotation on an instance without it."""

    labels: list[Catalogue] = Field(default_factory=list[Catalogue])
    """The message catalogues this plugin refuses out of, so a surface can render its codes.

    A pack's refusal reaches a browser under the pack's own code, and the browser holds no table
    for it. Contributing the catalogue is what puts one there: the host serves every code and its
    template, and a renderer that knows the code says its own sentence rather than repeating the
    English this process happened to mint."""

    @field_validator("api_version")
    @classmethod
    def _check_api_version(cls, value: int) -> int:
        """Reject a contribution written against a different revision of this contract."""
        if value != API_VERSION:
            raise ValueError(UNSUPPORTED_API_VERSION.render(version=value, host_version=API_VERSION))
        return value

    @model_validator(mode="after")
    def _check_ids(self) -> "Contribution":
        """Reject a contribution whose blocks or surfaces collide on an id."""
        _require_unique("block id", [*(op.spec.id for op in self.operators), *(se.spec.id for se in self.sensors)])
        _require_unique("storage scheme", [backend.scheme for backend in self.storage_backends])
        _require_unique("notifier id", [notifier.id for notifier in self.notifiers])
        _require_unique("connection kind id", [connection.id for connection in self.connection_kinds])
        _require_unique("source kind", [source.spec.kind for source in self.sources])
        _require_unique("format", list(self.formats))
        _require_unique("label prefix", [catalogue.prefix for catalogue in self.labels])
        return self

    @model_validator(mode="after")
    def _check_marks(self) -> "Contribution":
        """Reject a connection or source kind whose declared mark is not path data a browser may draw."""
        marks = [
            *((connection.id, connection.mark) for connection in self.connection_kinds),
            *((source.spec.kind, source.mark) for source in self.sources),
        ]
        for kind, mark in marks:
            refusal = mark_refusal(kind, mark)
            if refusal is not None:
                raise ValueError(refusal)
        return self

    @model_validator(mode="after")
    def _check_sources(self) -> "Contribution":
        """Reject a source kind whose class is not the one its hosting names, or that nothing hosts."""
        hosted = {SourceHosting.RECEIVED: ReceivedSource, SourceHosting.POLLED: PolledSource}
        for source in self.sources:
            contract = hosted.get(source.spec.hosting)
            if contract is None or not isinstance(source, contract):
                raise ValueError(
                    SOURCE_NOT_HOSTED.render(kind=repr(source.spec.kind), hosting=source.spec.hosting.value)
                )
        return self

    def block_ids(self) -> list[str]:
        """List every operator and sensor id this contribution registers."""
        return [*(operator.spec.id for operator in self.operators), *(sensor.spec.id for sensor in self.sensors)]


def _require_unique(label: str, values: list[str]) -> None:
    """Raise when a list of contributed ids contains a duplicate."""
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(DUPLICATE_ID.render(label=label, value=repr(value)))
        seen.add(value)


def merge_contributions(contributions: list[Contribution]) -> Contribution:
    """Merge every plugin's contribution into the single catalog the host dispatches from."""
    merged: dict[str, list[Any]] = {
        "operators": [],
        "sensors": [],
        "storage_backends": [],
        "notifiers": [],
        "connection_kinds": [],
        "sources": [],
        "labels": [],
    }
    for contribution in contributions:
        for surface, collected in merged.items():
            collected.extend(getattr(contribution, surface))
    formats: dict[str, FormatCheck] = {}
    _require_unique("format", [name for contribution in contributions for name in contribution.formats])
    for contribution in contributions:
        formats.update(contribution.formats)
    return Contribution(api_version=API_VERSION, formats=formats, **merged)
