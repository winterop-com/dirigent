"""Response compression: gzip on the fly for what the server writes, and negotiation for files built compressed."""

from fastapi import FastAPI
from starlette.middleware.gzip import DEFAULT_EXCLUDED_CONTENT_TYPES, GZipMiddleware

#: Below this a response is sent as it is: the gzip framing would outweigh the saving.
MINIMUM_BYTES = 1024

#: A middle level: the last levels cost several times the CPU for a few percent of size.
COMPRESS_LEVEL = 6

#: Bytes with no declared text form, which an artifact read streams as stored, often already compressed.
EXCLUDED_CONTENT_TYPES = (*DEFAULT_EXCLUDED_CONTENT_TYPES, "application/octet-stream", "application/vnd.apache.parquet")

#: The encodings a file may be stored in beside its original, preferred first, with each one's suffix.
PRECOMPRESSED = (("br", ".br"), ("gzip", ".gz"))


def install_compression(app: FastAPI) -> None:
    """Gzip every response a client accepts it for, unless it is small, a stream of events, or already encoded."""
    app.add_middleware(
        GZipMiddleware,
        minimum_size=MINIMUM_BYTES,
        compresslevel=COMPRESS_LEVEL,
        exclude_content_types=EXCLUDED_CONTENT_TYPES,
    )


def accepted_encodings(header: str) -> set[str]:
    """The content codings an ``Accept-Encoding`` header admits, without the ones it refuses with ``q=0``."""
    accepted: set[str] = set()
    for item in header.split(","):
        coding, _, parameters = item.partition(";")
        coding = coding.strip().lower()
        if not coding:
            continue
        quality = parameters.strip().lower()
        if quality.startswith("q=") and _refused(quality[2:]):
            continue
        accepted.add(coding)
    return accepted


def _refused(quality: str) -> bool:
    """Whether a quality value is zero, which is how a client says never."""
    try:
        return float(quality) == 0
    except ValueError:
        return False
