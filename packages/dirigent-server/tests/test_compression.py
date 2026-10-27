"""Compression of what the server writes: gzip for a client that accepts it, nothing for one that does not."""

from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from fastapi.testclient import TestClient

from dirigent_server.compression import accepted_encodings, install_compression

LARGE = "dirigent " * 1000


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/text")
    async def text() -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        return PlainTextResponse(LARGE)

    @app.get("/small")
    async def small() -> PlainTextResponse:  # pyright: ignore[reportUnusedFunction]
        return PlainTextResponse("dirigent")

    @app.get("/bytes")
    async def raw() -> Response:  # pyright: ignore[reportUnusedFunction]
        return Response(LARGE.encode(), media_type="application/octet-stream")

    @app.get("/events")
    async def events() -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        async def tail() -> AsyncIterator[str]:
            yield f"data: {LARGE}\n\n"

        return StreamingResponse(tail(), media_type="text/event-stream")

    install_compression(app)
    return app


def test_a_large_response_is_gzipped_for_a_client_that_accepts_it() -> None:
    response = TestClient(_app()).get("/text", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert int(response.headers["content-length"]) < len(LARGE)
    assert response.text == LARGE


def test_a_client_that_names_no_gzip_is_answered_uncompressed() -> None:
    response = TestClient(_app()).get("/text", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in response.headers


def test_a_small_response_is_sent_as_it_is() -> None:
    response = TestClient(_app()).get("/small", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in response.headers


def test_opaque_bytes_and_an_event_stream_are_never_compressed() -> None:
    client = TestClient(_app())
    for path in ("/bytes", "/events"):
        response = client.get(path, headers={"Accept-Encoding": "gzip"})
        assert "content-encoding" not in response.headers, path


def test_the_application_compresses_its_api_answers(client: TestClient) -> None:
    response = client.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"


def test_accept_encoding_drops_a_coding_refused_with_zero_quality() -> None:
    assert accepted_encodings("gzip, br;q=0, deflate;q=0.5, ") == {"gzip", "deflate"}
    assert accepted_encodings("") == set()
