/**
 * Reading one of this server's event streams.
 *
 * NOT `EventSource`. The browser's own client cannot set a header, and this API's streams are
 * resumed with `Last-Event-ID`; it also cannot be aborted except by closing it, and it
 * reconnects on its own schedule rather than the caller's. `fetch` plus a reader gives the
 * caller the abort signal, the resume cursor, and the end of the stream as a value.
 *
 * WHAT A CALLER GETS is a frame at a time -- the event name, the data, and the id the stream
 * last stated -- and nothing about what the data means. `runs/{id}/$events` names its frames
 * `attempt`, `log`, `run`, `end` and `expired`; deciding what those are is the screen's job,
 * not this module's.
 *
 * RESUMING. Only some frames carry an `id:`. The parser holds the last one it saw, so a
 * caller that reconnects passes it back as `after` and the server continues past it rather
 * than replaying it. A stream that ends is not a failure: `end` says the run settled, and
 * `expired` says the server closed the tail at its own wall-clock limit.
 */

import { ApiError, apiFetch, problemOf } from '@/lib/api'

/** One dispatched SSE event. */
export interface SseFrame {
    /** The event name. `message` when the stream named none, which is what the SSE default is. */
    event: string
    /** The payload. Several `data:` lines in one frame arrive joined by newlines. */
    data: string
    /** The id this stream last stated, or null before it has stated one. */
    id: string | null
}

/** The default event name a frame carries when the stream names none. */
export const DEFAULT_EVENT = 'message'

/** How the caller says where to resume and when to stop. */
export interface SseOptions {
    /** Abort the in-flight request. Closing the tail is the only way to stop it. */
    signal?: AbortSignal
    /**
     * The cursor to continue past, sent as `?after=` and as `Last-Event-ID`.
     *
     * Both, because the server accepts either and takes `after` first: the query parameter is
     * what a first connection states deliberately, and the header is what a reconnect resends.
     */
    after?: string | null
    /** Anything else the endpoint takes, such as `step` or `follow`. */
    query?: Record<string, string>
}

/** Accumulates lines into frames, holding the last stated id across them. */
export interface FrameParser {
    /** Feed one complete line, without its terminator. Yields a frame when that line ended one. */
    parseLine: (line: string) => Generator<SseFrame>
    /** The id the stream last stated, which is what a reconnect resumes past. */
    lastEventId: () => string | null
}

/**
 * Build a parser over one stream.
 *
 * Kept as a generator so the per-chunk loop and the final flush share identical parsing: a
 * terminal frame that arrives without its trailing blank line is exactly the frame that
 * matters on a truncated connection.
 *
 * A blank line dispatches. A line beginning with `:` is a comment, which is how a server keeps
 * an idle connection open, and it dispatches nothing. A frame whose data is empty dispatches
 * nothing either, which is what the SSE grammar says.
 */
export function frameParser(): FrameParser {
    let event = ''
    let data: string[] = []
    let lastId: string | null = null

    function* parseLine(line: string): Generator<SseFrame> {
        if (line === '') {
            if (data.length === 0) {
                event = ''
                return
            }
            const frame: SseFrame = { event: event || DEFAULT_EVENT, data: data.join('\n'), id: lastId }
            event = ''
            data = []
            yield frame
            return
        }
        if (line.startsWith(':')) return
        const colon = line.indexOf(':')
        const field = colon === -1 ? line : line.slice(0, colon)
        const raw = colon === -1 ? '' : line.slice(colon + 1)
        // One space after the colon is separator rather than payload; a second one is payload.
        const value = raw.startsWith(' ') ? raw.slice(1) : raw
        if (field === 'event') event = value
        else if (field === 'data') data.push(value)
        else if (field === 'id' && !value.includes('\0')) lastId = value
    }

    return { parseLine, lastEventId: () => lastId }
}

/**
 * Read a byte stream as SSE frames.
 *
 * The chunk boundaries a network hands back have nothing to do with line boundaries, so a
 * partial trailing line is held for the next read. A chunk that ends on a lone carriage return
 * is held too: it may be the first half of a CRLF pair, and splitting there would invent a
 * blank line and dispatch a frame early.
 */
export async function* readFrames(body: ReadableStream<Uint8Array>, parser: FrameParser): AsyncGenerator<SseFrame> {
    const reader = body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    try {
        for (;;) {
            // Reading a stream is sequential by definition: the next chunk does not exist until
            // this one has been handed over, so there is nothing here to run in parallel.
            // oxlint-disable-next-line no-await-in-loop
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            const held = buffer.endsWith('\r') ? '\r' : ''
            const usable = held === '' ? buffer : buffer.slice(0, -1)
            const lines = usable.split(/\r\n|\r|\n/)
            buffer = (lines.pop() ?? '') + held
            for (const line of lines) yield* parser.parseLine(line)
        }
        // Flush the decoder, releasing any buffered multibyte character, then parse whatever the
        // stream ended without terminating.
        buffer += decoder.decode()
        for (const line of buffer.split(/\r\n|\r|\n/)) yield* parser.parseLine(line)
        yield* parser.parseLine('')
    } finally {
        reader.releaseLock()
    }
}

/**
 * Open one of this API's event streams and yield its frames.
 *
 * A refusal arrives as an `ApiError` before the first frame, in the same shape every other
 * refusal in this app takes, so a screen renders it with the card it already has.
 */
export async function* streamSse(path: string, options: SseOptions = {}): AsyncGenerator<SseFrame> {
    const after = options.after ?? ''
    const search = new URLSearchParams(options.query)
    if (after !== '') search.set('after', after)
    const query = search.toString()
    const headers = new Headers({ accept: 'text/event-stream' })
    if (after !== '') headers.set('Last-Event-ID', after)

    const response = await apiFetch(query === '' ? path : `${path}?${query}`, {
        headers,
        signal: options.signal,
        cache: 'no-store',
    })
    if (!response.ok || response.body === null) {
        const body: unknown = await response.json().catch(() => null)
        throw new ApiError(problemOf(response.status, body, path))
    }
    yield* readFrames(response.body, frameParser())
}
