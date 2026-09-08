"""Server-side re-export of the logging configuration from dirigent-core."""

from dirigent_core.logging import PACKAGE_LOGGER, configure_logging, get_logger

__all__ = ["PACKAGE_LOGGER", "configure_logging", "get_logger"]
