"""Capturing what a local process printed: decode it, log it, store it, quote it."""

import asyncio
from collections.abc import Sequence
from typing import NamedTuple

from dirigent_plugin import ByteSink, StepContext

LOGGED_LINES = 40

FAILURE_TAIL_LINES = 5

#: What a scrubbed secret is replaced by, matching the marker the API redacts a connection with.
REDACTED = "***"


class Captured(NamedTuple):
    """One stream as an output carries it: the head that inlines, and the truth about the rest."""

    text: str
    """The head of the stream, as much of it as the instance lets a block inline."""

    total_bytes: int
    """How much the process printed, whether it inlined or not."""

    truncated: bool
    """Whether the text above is short of the stream; the artifact URI always holds all of it."""


def captured(payload: bytes, limit: int) -> Captured:
    """Cut one captured stream down to what may be inlined, and say what was cut."""
    return Captured(text=decode(payload[:limit]), total_bytes=len(payload), truncated=len(payload) > limit)


#: How much of the end of a stream is kept, for the lines a failure message quotes. The head
#: is what a block may inline; this is the other end, and together they bound what is held.
TAIL_BYTES = 8 * 1024

#: How much is read from a pipe at a time.
CHUNK_BYTES = 64 * 1024


class Logged(NamedTuple):
    """What a stream put into the run log while it was still being read."""

    lines: int
    """Non-blank lines the stream carried."""

    live: int
    """How many of them reached the run log as they arrived."""


class Drained(NamedTuple):
    """What was kept of a stream that was written through to storage as it arrived."""

    head: bytes
    """The beginning, as much as may be inlined."""

    tail: bytes
    """The end, for the lines a failure quotes."""

    total_bytes: int
    """How much the process printed, all of which reached storage."""

    logged: Logged | None = None
    """What was already logged live, or ``None`` when the stream was not logged as it arrived."""

    def captured(self, limit: int) -> Captured:
        """Present the head as an output carries it, against what the whole stream was."""
        return Captured(
            text=decode(self.head[:limit]),
            total_bytes=self.total_bytes,
            truncated=self.total_bytes > limit,
        )


class Ends:
    """Both ends of a stream and its size, holding nothing of the middle.

    A stream is fed in as it arrives. What is kept is the head, which is what may be inlined,
    and the last few kilobytes, which is what a failure message quotes.
    """

    def __init__(self, head_limit: int) -> None:
        """Keep at most this much of the beginning."""
        self._head_limit = head_limit
        self._head = bytearray()
        self._tail = bytearray()
        self.total_bytes = 0

    def add(self, chunk: bytes) -> None:
        """Take one piece of the stream."""
        self.total_bytes += len(chunk)
        if len(self._head) < self._head_limit:
            self._head.extend(chunk[: self._head_limit - len(self._head)])
        self._tail.extend(chunk)
        if len(self._tail) > TAIL_BYTES:
            del self._tail[: len(self._tail) - TAIL_BYTES]

    def drained(self, live: "LiveLines | None" = None) -> Drained:
        """Present what was kept, and what a live logger already said about it."""
        return Drained(
            head=bytes(self._head),
            tail=bytes(self._tail),
            total_bytes=self.total_bytes,
            logged=live.logged() if live is not None else None,
        )


class LiveLines:
    """Puts the first lines of a stream into the run log as the process prints them.

    Bytes are fed in as they are read. Every complete non-blank line is counted, and the
    first ``budget`` of them are logged where they happen, so a run screen shows a long
    command working rather than everything it printed at the moment it exited. Past the
    budget nothing is held: the line is counted and dropped, and the other end of the stream
    reaches the log when the stream closes.
    """

    def __init__(
        self,
        ctx: StepContext,
        stream: str,
        *,
        budget: int = LOGGED_LINES // 2,
        redact: Sequence[str] = (),
    ) -> None:
        """Log to this stream's level, redacting the strings the block handed the process."""
        self._log = ctx.log.info if stream == "stdout" else ctx.log.warning
        self._stream = stream
        self._budget = budget
        self._redact = redact
        self._pending = bytearray()
        self._nonblank = False
        self._lines = 0
        self._live = 0

    def feed(self, chunk: bytes) -> None:
        """Take one piece of the stream, logging every complete line it completes."""
        start = 0
        while (cut := chunk.find(b"\n", start)) >= 0:
            self._take(chunk[start:cut])
            self._finish()
            start = cut + 1
        self._take(chunk[start:])

    def close(self) -> None:
        """Log a last line the process left without a newline."""
        self._finish()

    def logged(self) -> Logged:
        """How many lines the stream carried and how many of them are in the log already."""
        return Logged(lines=self._lines, live=self._live)

    def _take(self, piece: bytes) -> None:
        """Hold a piece of the line being read, or only whether it has anything in it."""
        if not piece:
            return
        self._nonblank = self._nonblank or bool(piece.strip())
        if self._live < self._budget:
            self._pending.extend(piece)

    def _finish(self) -> None:
        """End the line being read: count it, and log it while the budget lasts."""
        if self._nonblank:
            self._lines += 1
            if self._live < self._budget:
                self._live += 1
                self._log(scrub(decode(bytes(self._pending)).rstrip("\r"), self._redact), stream=self._stream)
        self._pending.clear()
        self._nonblank = False


async def drain(
    reader: "asyncio.StreamReader | None",
    sink: ByteSink,
    *,
    head_limit: int,
    live: LiveLines | None = None,
) -> Drained:
    """Read one pipe to its end, writing it through to storage and keeping both ends.

    Nothing holds the whole stream. A command that prints a gigabyte is a file in storage and
    two bounded buffers here, rather than a gigabyte in the worker.

    With a ``live`` logger the lines go into the run log as they are read, up to its budget.
    """
    ends = Ends(head_limit)
    while reader is not None:
        chunk = await reader.read(CHUNK_BYTES)
        if not chunk:
            break
        ends.add(chunk)
        if live is not None:
            live.feed(chunk)
        await sink.write(chunk)
    if live is not None:
        live.close()
    return ends.drained(live)


def decode(payload: bytes) -> str:
    """Render captured bytes as text without ever failing on what a process printed."""
    return payload.decode("utf-8", errors="replace")


def lines_of(payload: bytes) -> list[str]:
    """Split a captured stream into its non-blank lines."""
    return [line for line in decode(payload).splitlines() if line.strip()]


def scrub(text: str, secrets: Sequence[str] = ()) -> str:
    """Replace every occurrence of a secret with the redaction marker.

    A tool prints what it was given. ``git`` echoes a remote URL, an ssh command line and,
    when a credential is wrong, sometimes the credential itself, so a block that hands a
    process a secret hands this the same strings and nothing reaches a log or a failure
    message with them still in it. Longest first, so a secret that contains another is
    replaced whole rather than left in pieces.
    """
    for secret in sorted((one for one in secrets if one), key=len, reverse=True):
        text = text.replace(secret, REDACTED)
    return text


def tail(
    payload: bytes,
    *,
    count: int = FAILURE_TAIL_LINES,
    separator: str = " / ",
    redact: Sequence[str] = (),
) -> str:
    """Take the last few lines of a stream, which is what a failure message wants."""
    return scrub(separator.join(lines_of(payload)[-count:]), redact)


async def store(ctx: StepContext, uri: str, payload: bytes) -> None:
    """Write one captured stream to storage, so it outlives the worker that produced it."""
    async with ctx.storage.open_write(uri) as sink:
        await sink.write(payload)


def log_stream(ctx: StepContext, stream: str, drained: Drained, redact: Sequence[str] = ()) -> None:
    """Put what the process printed into the run's log, from both ends of the stream.

    A caller that read the stream through to storage holds only its two ends, and identical
    ends are how one small enough to be held whole says so. The whole of a stream is elided
    by line count; what is held in two pieces can only be logged as two pieces.

    A stream that was logged live already has its first lines in the log: this adds the last
    of them, and only the ones that were never said.

    ``redact`` names the strings a block handed the process that must not reach the log.
    """
    log = ctx.log.info if stream == "stdout" else ctx.log.warning
    half = LOGGED_LINES // 2
    if drained.logged is not None:
        remaining = drained.logged.lines - drained.logged.live
        if remaining <= 0:
            return
        last = lines_of(drained.tail)[-min(remaining, half) :]
        if remaining > len(last):
            log(f"... {remaining - len(last)} more lines, see the {stream} artifact ...", stream=stream)
        for line in last:
            log(scrub(line, redact), stream=stream)
        return
    if drained.head == drained.tail:
        lines = lines_of(drained.head)
        if not lines:
            return
        shown = lines
        if len(lines) > LOGGED_LINES:
            shown = [
                *lines[:half],
                f"... {len(lines) - LOGGED_LINES} more lines, see the {stream} artifact ...",
                *lines[-half:],
            ]
        for line in shown:
            log(scrub(line, redact), stream=stream)
        return
    first = lines_of(drained.head)
    last = lines_of(drained.tail)
    if not first and not last:
        return
    for line in first[:half]:
        log(scrub(line, redact), stream=stream)
    log(f"... the middle is not in the log, see the {stream} artifact ...", stream=stream)
    for line in last[-half:]:
        log(scrub(line, redact), stream=stream)
