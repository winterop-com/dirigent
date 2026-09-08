"""The web UI: a built single-page bundle, served off the API server itself.

The bundle mounts in two pieces, and the order of the two matters. Starlette matches routes
in registration order, so ``/assets`` is registered with the fixed paths, ahead of every
router, and the shell is mounted at ``/`` after them, where it claims whatever is left.

The UI routes with clean paths, so ``/runs/<id>`` is a route inside the bundle rather than a
file on disk. Nothing serves it, and a deep link or a refresh would answer 404 -- so the 404
handler serves the shell for a navigation that no route and no file claimed. A navigation is
a GET or HEAD, outside the reserved prefixes, whose ``Accept`` names an HTML type: a browser
navigating always names one, and ``fetch`` defaults to ``*/*``, which is not one. Everything
else keeps the problem document. Precedence is unchanged by any of it: an API route wins,
then a real file, and the shell is the last resort.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from dirigent_core import __version__
from dirigent_core.config import Settings
from dirigent_server.errors import http_error

#: The file whose presence means a bundle was built, rather than the directory existing.
INDEX_FILENAME = "index.html"

#: Where vite emits every content-hashed file, and the path they are served from.
ASSETS_MOUNT_PATH = "/assets"

CONFIG_PATH = "/config.json"
FAVICON_PATH = "/favicon.ico"

#: Icons the shell may reference, most specific first; the first one present answers
#: ``/favicon.ico``, which browsers ask for whatever the document declares.
FAVICON_FILENAMES = (("favicon.ico", "image/x-icon"), ("favicon.svg", "image/svg+xml"), ("favicon-32.png", "image/png"))

#: A content-hashed file's name changes whenever its bytes do, so it never goes stale.
IMMUTABLE = "public, max-age=31536000, immutable"

#: The shell names the current hashes, so a cached one loads files a rebuild deleted.
REVALIDATE = "no-cache"

#: The media types a navigating browser names, and a ``fetch`` default of ``*/*`` does not.
HTML_ACCEPT = ("text/html", "application/xhtml+xml")

#: Paths the shell must never answer for: a fetch that got HTML instead of JSON fails three
#: layers away, and a missing hashed asset answered with the page that asked for it loops.
RESERVED_PREFIXES = (
    "/health",
    "/hooks",
    "/docs",
    "/redoc",
    "/openapi.json",
    ASSETS_MOUNT_PATH,
    CONFIG_PATH,
    FAVICON_PATH,
)

BUNDLE_MISSING = (
    "The dirigent web UI is enabled and no bundle is built. Build one with `make ui`, "
    "or set DIRIGENT_UI_ENABLED=false to run this instance as an API only. "
    "The API itself is unaffected and is serving normally."
)

#: Where the built bundle lives inside the installed package: vite's ``build.outDir``.
PACKAGED_STATIC = Path(__file__).resolve().parent / "static"

#: Where vite leaves it in a checkout, so the dev loop needs no install step.
CHECKOUT_STATIC = Path(__file__).resolve().parents[2] / "frontend" / "dist"

MOUNT_NAME = "ui"
ASSETS_MOUNT_NAME = "ui-assets"


class UiStaticFiles(StaticFiles):
    """Static files with a cache policy stated rather than left to a browser's heuristic.

    Starlette sends only ETag and Last-Modified, and a response with no ``Cache-Control`` is
    heuristically cacheable, so the policy is written down: the hashed asset tree is
    immutable, and everything else revalidates.
    """

    def __init__(self, *, directory: Path, html: bool = False, immutable: bool = False) -> None:
        """Serve one directory, either as the hashed asset tree or as the shell's root.

        The directory may not exist yet: a checkout serves the bundle a later ``make ui``
        writes, so existence is a per-request question rather than a startup one.
        """
        super().__init__(directory=directory, html=html, check_dir=False)
        self.immutable = immutable

    async def check_config(self) -> None:
        """Verify the directory only once it exists; before that, every path is a miss."""
        if self.directory is not None and Path(self.directory).is_dir():
            await super().check_config()

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Answer one static file, stating how long it may be held."""
        response = await super().get_response(path, scope)
        served = 200 <= response.status_code < 400
        response.headers["cache-control"] = IMMUTABLE if self.immutable and served else REVALIDATE
        return response


def static_dir(settings: Settings) -> Path | None:
    """The built bundle this instance serves, or None when it has none to serve.

    The installed package's own ``static/`` wins over a checkout's ``frontend/dist``.
    """
    if not settings.ui_enabled:
        return None
    for candidate in (PACKAGED_STATIC, CHECKOUT_STATIC):
        if (candidate / INDEX_FILENAME).is_file():
            return candidate
    return None


def serving_root(settings: Settings) -> Path | None:
    """Where this instance's bundle lives, or would land if one were built.

    A bundle built later must be served without a restart, so the answer does not require
    ``index.html`` to exist yet: a directory a build writes into is enough. A built bundle
    keeps the same precedence ``static_dir`` states; with none, a checkout's ``frontend/``
    names where ``make ui`` will put one, and an installed package's own ``static/`` is where
    a wheel would have carried one.
    """
    if not settings.ui_enabled:
        return None
    built = static_dir(settings)
    if built is not None:
        return built
    if CHECKOUT_STATIC.parent.is_dir():
        return CHECKOUT_STATIC
    if PACKAGED_STATIC.is_dir():
        return PACKAGED_STATIC
    return None


def mount_ui_assets(app: FastAPI, settings: Settings) -> None:
    """Register the UI's fixed paths, before every router: the asset tree and the config document."""
    if not settings.ui_enabled:
        return
    _add_config_route(app, settings)
    directory = serving_root(settings)
    if directory is None:
        return
    app.mount(
        ASSETS_MOUNT_PATH,
        UiStaticFiles(directory=directory / ASSETS_MOUNT_PATH.lstrip("/"), immutable=True),
        name=ASSETS_MOUNT_NAME,
    )
    _add_favicon_route(app, directory)


def mount_ui_shell(app: FastAPI, settings: Settings) -> None:
    """Mount the shell at ``/``, after every router, and answer a client route with it."""
    if not settings.ui_enabled:
        return
    directory = serving_root(settings)
    if directory is None:
        _add_refusal_route(app)
        return
    app.mount("/", UiStaticFiles(directory=directory, html=True), name=MOUNT_NAME)
    _add_shell_fallback(app, settings, directory / INDEX_FILENAME)


def _add_config_route(app: FastAPI, settings: Settings) -> None:
    """Answer what the bundle cannot hardcode: where this instance's API is, and its version."""

    @app.get(CONFIG_PATH, include_in_schema=False)
    async def config() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return JSONResponse(
            {"api_prefix": settings.api_prefix, "version": __version__},
            headers={"cache-control": REVALIDATE},
        )


def _add_favicon_route(app: FastAPI, directory: Path) -> None:
    """Serve the first icon the bundle carries at ``/favicon.ico``."""
    icons = [(directory / name, media_type) for name, media_type in FAVICON_FILENAMES]

    @app.get(FAVICON_PATH, include_in_schema=False)
    async def favicon() -> FileResponse:  # pyright: ignore[reportUnusedFunction]
        for path, media_type in icons:
            if path.is_file():
                return FileResponse(path, media_type=media_type, headers={"cache-control": REVALIDATE})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="this bundle carries no icon")


def _add_refusal_route(app: FastAPI) -> None:
    """Answer ``/`` with one sentence naming the command that builds the bundle."""

    @app.get("/", include_in_schema=False)
    async def missing() -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        return PlainTextResponse(
            BUNDLE_MISSING,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            headers={"cache-control": REVALIDATE},
        )


def _add_shell_fallback(app: FastAPI, settings: Settings, index: Path) -> None:
    """Serve the shell for a navigation nothing else claimed, and leave every other 404 alone.

    The index is read per request, so a bundle built after startup is served without a
    restart, and one a rebuild has momentarily emptied refuses honestly instead of erroring.
    ``/`` itself answers the refusal to any GET, navigation or not, because it is the one
    path a person and a probe both try first.
    """
    reserved = (settings.api_prefix, *RESERVED_PREFIXES)

    async def shell_or_404(request: Request, error: Exception) -> Response:
        at_root = request.url.path == "/" and request.method in ("GET", "HEAD")
        if (_is_navigation(request) or at_root) and not request.url.path.startswith(reserved):
            if index.is_file():
                return FileResponse(index, media_type="text/html", headers={"cache-control": REVALIDATE})
            if at_root or _is_navigation(request):
                return PlainTextResponse(
                    BUNDLE_MISSING,
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    headers={"cache-control": REVALIDATE},
                )
        return await http_error(request, error)

    app.add_exception_handler(status.HTTP_404_NOT_FOUND, shell_or_404)


def _is_navigation(request: Request) -> bool:
    """Whether this request is a browser asking for a page, rather than code asking for data."""
    if request.method not in ("GET", "HEAD"):
        return False
    accepted = request.headers.get("accept", "")
    return any(media_type in accepted for media_type in HTML_ACCEPT)
