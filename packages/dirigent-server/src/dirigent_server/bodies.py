"""Reading a request's body under a cap, for the routes a stranger may call."""

from fastapi import Request


async def read_capped(request: Request, limit: int) -> bytes:
    """Read the body, stopping one byte past the limit rather than after all of it.

    ``request.body()`` buffers whatever arrives before the size can be checked, so an
    unauthenticated caller could make the process allocate a gigabyte to be told a megabyte
    is the maximum. What comes back may be longer than the limit, which is how a caller
    learns the body was too large.
    """
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            break
    return b"".join(chunks)
