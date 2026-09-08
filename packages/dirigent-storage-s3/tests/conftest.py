"""Re-exports the s3-lane fixtures so pytest collects them."""

from s3server import backend, config, s3_server

__all__ = ["backend", "config", "s3_server"]
