"""Where a document comes from: a file, a URL, or standard input."""

import sys
from pathlib import Path
from typing import Final

import httpx2
from pydantic import BaseModel, ConfigDict

from dirigent_client.enums import ProvenanceSource

STDIN: Final = "-"
FETCH_TIMEOUT: Final = 30.0


class SourceError(Exception):
    """A document could not be read from where it was said to be."""


class Document(BaseModel):
    """One document's text, and where it came from."""

    model_config = ConfigDict(frozen=True)

    text: str
    source: ProvenanceSource
    ref: str

    @property
    def label(self) -> str:
        """Render the origin for a plan line or an error message."""
        return self.ref


def is_url(reference: str) -> bool:
    """Report whether a reference names a URL rather than a path."""
    return reference.startswith(("http://", "https://"))


def read_document(reference: str) -> Document:
    """Read a document from a file, a URL, or standard input."""
    if reference == STDIN:
        text = sys.stdin.read()
        if not text.strip():
            raise SourceError("nothing arrived on standard input")
        return Document(text=text, source=ProvenanceSource.API, ref="(stdin)")
    if is_url(reference):
        return Document(text=fetch(reference), source=ProvenanceSource.URL, ref=reference)
    path = Path(reference)
    if not path.is_file():
        raise SourceError(f"{reference} is neither a file, a URL, nor '-' for standard input")
    return Document(text=path.read_text(), source=ProvenanceSource.FILE, ref=str(path))


def fetch(url: str) -> str:
    """Fetch a document over HTTP."""
    try:
        response = httpx2.get(url, timeout=FETCH_TIMEOUT, follow_redirects=True)
        response.raise_for_status()
    except httpx2.HTTPError as error:
        raise SourceError(f"{url} could not be fetched: {type(error).__name__}: {error}") from error
    return response.text


def read_path(path: Path) -> Document:
    """Read a document from a path already known to be one, keeping its provenance."""
    return Document(text=path.read_text(), source=ProvenanceSource.FILE, ref=str(path))


def looks_like_a_document(reference: str) -> bool:
    """Report whether an argument names a document rather than a pipeline.

    Unambiguous only because a pipeline name is a DNS label: it can never contain ``/``,
    ``.``, or a scheme.
    """
    return reference == STDIN or is_url(reference) or Path(reference).is_file()
