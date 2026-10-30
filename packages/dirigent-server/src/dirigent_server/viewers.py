"""The two API viewers, each bundle pinned to one release and to the bytes that release published.

A browser refuses a bundle whose bytes do not match its ``integrity``, so a version and its hashes
change together. The content security policy names these same URLs and nothing else on the CDN.
"""

import base64
import hashlib
import html
from typing import Final

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(include_in_schema=False)

SWAGGER_JS: Final = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.3/swagger-ui-bundle.js"
SWAGGER_JS_INTEGRITY: Final = "sha384-h00llMzD1afyNow1pDmnZKlHsUZgp9KE9HXLFXF2CvbwsBY0+WBO4f75SfGwvM4K"

SWAGGER_CSS: Final = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.33.3/swagger-ui.css"
SWAGGER_CSS_INTEGRITY: Final = "sha384-Ov4/wv3j2bmct8cDc5X4ngJZohVPzEmc6uDPH8WeljUxO5vtoykvMEfbu9Vh6RaW"

REDOC_JS: Final = "https://cdn.jsdelivr.net/npm/redoc@2.5.4/bundles/redoc.standalone.js"
REDOC_JS_INTEGRITY: Final = "sha384-w447zOpYfw/1Tv/5AK9NfHTlQIqE3RVR6KY62jCyy9zNDgO64cMwGGP1Fj0zJVf5"

#: Starts Swagger UI, reading the document's address off the page so that this text never varies.
SWAGGER_BOOTSTRAP: Final = """
window.ui = SwaggerUIBundle({
    url: document.getElementById('swagger-ui').dataset.spec,
    dom_id: '#swagger-ui',
    layout: 'BaseLayout',
    deepLinking: true,
    showExtensions: true,
    showCommonExtensions: true,
    validatorUrl: null,
    presets: [SwaggerUIBundle.presets.apis, SwaggerUIBundle.SwaggerUIStandalonePreset],
});
"""

#: The content security policy's source for that bootstrap, the one inline script either page has.
_BOOTSTRAP_DIGEST: Final = base64.b64encode(hashlib.sha256(SWAGGER_BOOTSTRAP.encode()).digest()).decode()
SWAGGER_BOOTSTRAP_SOURCE: Final = f"'sha256-{_BOOTSTRAP_DIGEST}'"


def _document_url(request: Request) -> str:
    """Where the OpenAPI document is, written safely for an HTML attribute."""
    return html.escape(f"{request.scope.get('root_path', '')}{request.app.openapi_url}", quote=True)


@router.get("/docs")
async def swagger_ui(request: Request) -> HTMLResponse:
    """Serve Swagger UI."""
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="{SWAGGER_CSS}" integrity="{SWAGGER_CSS_INTEGRITY}" crossorigin="anonymous">
<title>{html.escape(request.app.title)} - Swagger UI</title>
</head>
<body>
<div id="swagger-ui" data-spec="{_document_url(request)}"></div>
<script src="{SWAGGER_JS}" integrity="{SWAGGER_JS_INTEGRITY}" crossorigin="anonymous"></script>
<script>{SWAGGER_BOOTSTRAP}</script>
</body>
</html>
"""
    )


@router.get("/redoc")
async def redoc(request: Request) -> HTMLResponse:
    """Serve ReDoc."""
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(request.app.title)} - ReDoc</title>
<style>body {{ margin: 0; padding: 0; }}</style>
</head>
<body>
<redoc spec-url="{_document_url(request)}"></redoc>
<script src="{REDOC_JS}" integrity="{REDOC_JS_INTEGRITY}" crossorigin="anonymous"></script>
</body>
</html>
"""
    )
