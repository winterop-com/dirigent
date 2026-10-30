"""Where a JSON Schema ``$ref`` may lead: into its own document and the drafts the library ships.

A validator built without a registry retrieves a ``$ref`` it cannot resolve over HTTP, on
whichever process is validating. A schema is written by whoever can apply a document, so that
is a request from the server's network to an address they chose. Every validator here is built
with this registry, which retrieves nothing; the library adds its bundled metaschemas to it.
"""

from typing import Any, Final

from referencing import Registry
from referencing.exceptions import Unresolvable

LOCAL_REFERENCES: Final[Registry[Any]] = Registry()

__all__ = ["LOCAL_REFERENCES", "Unresolvable"]
