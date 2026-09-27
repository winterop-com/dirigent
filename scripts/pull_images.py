"""Pull container images, trying again when the registry drops the connection.

A runner reaches a public registry from an address it shares with every other job on that
machine, and such a pull answers a reset connection or a rate limit often enough to redden a
build that is otherwise green. Each reference is pulled again after a growing pause:

    python3 scripts/pull_images.py postgres:17-alpine redpandadata/redpanda:v24.2.18

Every reference is attempted before the script gives up, so an image nobody can reach is
named rather than hidden behind the first failure.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time

#: How many times one image is pulled before the script gives up on it.
ATTEMPTS = 4

#: Seconds waited after the first failure, multiplied by the attempt number after that.
BACKOFF_SECONDS = 5


def pull(image: str, attempts: int) -> bool:
    """Pull one image, answering whether it arrived."""
    for attempt in range(1, attempts + 1):
        if subprocess.run(["docker", "pull", "--quiet", image], check=False).returncode == 0:
            return True
        print(f"pull failed: {image} (attempt {attempt} of {attempts})", file=sys.stderr, flush=True)
        if attempt < attempts:
            time.sleep(BACKOFF_SECONDS * attempt)
    return False


def main() -> int:
    """Pull every image named on the command line, failing once at the end."""
    parser = argparse.ArgumentParser(description="Pull container images, retrying a dropped pull.")
    parser.add_argument("images", nargs="*", help="image references, tag or digest")
    parser.add_argument("--attempts", type=int, default=ATTEMPTS, help=f"tries per image (default {ATTEMPTS})")
    arguments = parser.parse_args()

    unreachable = [image for image in arguments.images if not pull(image, arguments.attempts)]
    for image in unreachable:
        print(f"unreachable: {image}", file=sys.stderr)
    return 1 if unreachable else 0


if __name__ == "__main__":
    raise SystemExit(main())
