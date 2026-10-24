"""Reading the parts of an HTTP request that every surface reads the same way."""

from collections.abc import Iterable
from urllib.parse import parse_qsl

from pydantic import JsonValue


def gather_values(pairs: Iterable[tuple[str, str]]) -> dict[str, JsonValue]:
    """Fold name-value pairs into a map: one value a string, a repeated name a list in order."""
    gathered: dict[str, list[str]] = {}
    for name, value in pairs:
        gathered.setdefault(name, []).append(value)
    return {name: values[0] if len(values) == 1 else list(values) for name, values in gathered.items()}


def form_values(text: str) -> dict[str, JsonValue]:
    """Read an ``application/x-www-form-urlencoded`` body the way a query string is read."""
    return gather_values(parse_qsl(text, keep_blank_values=True))


def media_type(content_type: str | None) -> tuple[str | None, dict[str, str]]:
    """Split a content-type header into its lowercased media type and its parameters."""
    if not content_type:
        return None, {}
    head, *rest = content_type.split(";")
    params: dict[str, str] = {}
    for part in rest:
        name, _, value = part.partition("=")
        if name.strip():
            params[name.strip().lower()] = value.strip().strip('"')
    media = head.strip().lower()
    return (media or None), params
