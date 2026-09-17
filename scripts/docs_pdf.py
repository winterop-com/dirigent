"""Build the docs and print the basics tutorial to ``site/basics.pdf``.

The page is printed from the built site rather than from Markdown, so the PDF carries the
same rendering, screenshots and code blocks the site does. Chromium is driven through
Playwright, which is layered in at call time rather than locked into the workspace:

    uv run --with playwright playwright install chromium
    uv run --with playwright python scripts/docs_pdf.py

``--skip-build`` prints from a ``site/`` that is already built, which is what CI does after
its own ``mkdocs build``.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

#: The repository root, one level above this script.
ROOT = Path(__file__).resolve().parent.parent

#: Where mkdocs writes the site, and where the PDF lands beside it.
SITE = ROOT / "site"

#: The page to print, as a path under the built site.
PAGE = "basics/"

#: The file the PDF is written to.
PDF = SITE / "basics.pdf"

#: Below this the print produced a blank or broken page rather than the tutorial.
LEAST_PLAUSIBLE_BYTES = 200_000


def build() -> None:
    """Build the site the way CI builds it: strict, and with Material's notice silenced."""
    subprocess.run(
        ["mkdocs", "build", "--strict"],
        cwd=ROOT,
        check=True,
        env={**os.environ, "NO_MKDOCS_2_WARNING": "1"},
    )


class Quiet(http.server.SimpleHTTPRequestHandler):
    """The static handler with its per-request logging dropped."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Say nothing: the script's own record is the output."""


def serve(directory: Path) -> tuple[socketserver.TCPServer, int]:
    """Serve a directory on a port the OS picks, and hand back the server and that port."""
    handler = functools.partial(Quiet, directory=str(directory))
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = socketserver.TCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


def render(url: str, target: Path) -> None:
    """Print one URL to one PDF with headless Chromium."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        # The print stylesheet is what decides the layout; the screen one would carry the
        # navigation into the paper.
        page.emulate_media(media="print")
        page.pdf(
            path=str(target),
            format="A4",
            print_background=True,
            margin={"top": "14mm", "bottom": "14mm", "left": "12mm", "right": "12mm"},
        )
        browser.close()


def pages(pdf: Path) -> int:
    """Count the pages a Chromium-written PDF holds, from its uncompressed page tree."""
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf.read_bytes()))


def main() -> int:
    """Build, print, and say what landed."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-build", action="store_true", help="print from the site already built")
    arguments = parser.parse_args()

    if not arguments.skip_build:
        build()
    if not (SITE / PAGE / "index.html").exists():
        print(f"{SITE / PAGE} is not built; run without --skip-build", file=sys.stderr)
        return 1

    server, port = serve(SITE)
    try:
        render(f"http://127.0.0.1:{port}/{PAGE}", PDF)
    finally:
        server.shutdown()

    written = PDF.stat().st_size
    print(json.dumps({"kind": "docs.pdf", "path": str(PDF.relative_to(ROOT)), "bytes": written, "pages": pages(PDF)}))
    if written < LEAST_PLAUSIBLE_BYTES:
        print(f"{PDF} is only {written} bytes, which is too small to be the tutorial", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
