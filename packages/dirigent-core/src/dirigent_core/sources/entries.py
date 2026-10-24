"""A hand run's entry: the source it enters at, and the input it gives there or the sample it falls back to."""

from collections.abc import Mapping
from datetime import datetime
from typing import cast

from pydantic import JsonValue, ValidationError

from dirigent_common import JsonMap
from dirigent_core.engine.definition import PipelineDefinition
from dirigent_core.engine.runs import Entry, RunCreationError
from dirigent_core.messages import (
    ENTRY_AMBIGUOUS,
    ENTRY_INPUT_REFUSED,
    ENTRY_NOT_A_SOURCE,
    ENTRY_ON_NO_SOURCES,
    SAMPLE_NOT_AN_OBJECT,
    UNKNOWN_KIND,
)
from dirigent_core.sources.rules import source_config
from dirigent_plugin.sources import AnySource

#: What a hand run's received attempt logs.
BY_HAND = "received by hand"


class EntryRefused(RunCreationError):
    """A hand run named a source it cannot enter at, or gave an input its kind cannot make whole."""

    status = 422


def hand_entry(
    definition: PipelineDefinition,
    kinds: Mapping[str, AnySource],
    step: str | None,
    given: JsonValue,
    *,
    received_at: datetime,
) -> Entry | None:
    """Read where a hand run enters and what arrives there, or nothing for a pipeline with no sources.

    With no step named, the pipeline's only source is entered. With no input given, the
    source's sample is, and with no sample either, the least input the kind can make whole.
    """
    sources = definition.sources
    if not sources:
        if step is not None or given is not None:
            raise EntryRefused(ENTRY_ON_NO_SOURCES, code=repr(definition.code))
        return None
    if step is None:
        if len(sources) > 1:
            raise EntryRefused(ENTRY_AMBIGUOUS, code=repr(definition.code), sources=", ".join(sources))
        step = sources[0]
    if step not in sources:
        raise EntryRefused(ENTRY_NOT_A_SOURCE, step=repr(step), code=repr(definition.code), sources=", ".join(sources))
    declared = definition.steps[step]
    node = declared.source
    kind = kinds.get(node.kind) if node is not None else None
    if node is None or kind is None:
        known = ", ".join(sorted(kinds)) or "none are installed"
        raise EntryRefused(UNKNOWN_KIND, kind=repr(node.kind if node else step), known=known)
    written = given if given is not None else (declared.sample if declared.sample is not None else {})
    try:
        if not isinstance(written, dict):
            raise ValueError(SAMPLE_NOT_AN_OBJECT.render(kind=type(written).__name__))
        made = kind.complete(source_config(kind, node.config), cast("JsonMap", written), received_at=received_at)
    except (ValueError, ValidationError) as error:
        raise EntryRefused(ENTRY_INPUT_REFUSED, step=repr(step), kind=repr(node.kind), detail=_first(error)) from error
    return Entry(step=step, output=cast("JsonMap", made.model_dump(mode="json")), via="hand", note=BY_HAND)


def _first(error: Exception) -> str:
    """Reduce a refusal to the part a person reads."""
    if isinstance(error, ValidationError):
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        return f"{where}: {first['msg']}" if where else str(first["msg"])
    return str(error).strip().splitlines()[0] if str(error).strip() else type(error).__name__
