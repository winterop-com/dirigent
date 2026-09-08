"""Dirigent core: configuration, the baseline schema, and the migrations that create it."""

from importlib.metadata import PackageNotFoundError, version

from dirigent_core.config import Settings, get_settings, reset_settings_cache
from dirigent_core.database import create_engine, create_session_factory, ping, session_scope
from dirigent_core.ids import uuid7
from dirigent_core.models import Base

try:
    __version__ = version("dirigent-core")
except PackageNotFoundError:  # pragma: no cover - only when running from a source tree
    __version__ = "0.0.0"

__all__ = [
    "Base",
    "Settings",
    "__version__",
    "create_engine",
    "create_session_factory",
    "get_settings",
    "ping",
    "reset_settings_cache",
    "session_scope",
    "uuid7",
]
