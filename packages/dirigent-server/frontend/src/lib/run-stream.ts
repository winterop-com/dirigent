/**
 * Keeping exactly one event stream open on one run.
 *
 * ONE STREAM PER OPEN RUN, AND NEVER A SECOND. `GET /runs/{id}/$events` is already multiplexed:
 * it carries the attempt transitions, the log lines and the run's ending down one connection,
 * in order. A second stream for the log pane, or one per panel, would cost this instance a poll
 * loop each -- the server caps a principal at eight of them -- and would deliver the same story
 * twice with no ordering between the copies. So this is a sequential loop by construction:
 * `follow` awaits one connection to its end before it opens another, and there is no path
 * through it that has two open at once.
 *
 * A RECONNECT RESUMES, IT DOES NOT REPLAY. The cursor is read fresh from the caller before every
 * connect, which is the last log id the reducer applied; attempt and run frames carry no id and
 * are replayed by the server on purpose, and the reducer dedupes them by their own ids.
 *
 * `end` IS THE RUN, `expired` IS THE CONNECTION. The server sends `end` when the run settles and
 * `expired` when it closes a stream at its own wall-clock limit with the run still going. An
 * `expired` frame is about the connection, so it never reaches the screen: it reopens the stream
 * from the cursor. The caller still confirms `end` against the run it has, since only a settled
 * run is the end of the story.
 */

import { eventsPath } from '@/lib/runs'
import type { StreamState } from '@/lib/run-detail'
import { streamSse, type SseFrame } from '@/lib/sse'

/** Where the first reconnect waits. */
export const BACKOFF_FLOOR_MS = 500

/** The longest a reconnect waits, however many times it has failed. */
export const BACKOFF_CEILING_MS = 15_000

/** How long before reopening a stream the server closed at its own wall-clock limit. */
export const CONTINUE_DELAY_MS = 250

/** How long a reconnect waits after `failures` consecutive failed connections. */
export function backoffFor(failures: number): number {
    if (failures <= 0) return 0
    return Math.min(BACKOFF_CEILING_MS, BACKOFF_FLOOR_MS * 2 ** (failures - 1))
}

/** How a connection is opened. The real one is `streamSse`; a test passes its own. */
export type StreamSource = (
    path: string,
    options: { signal?: AbortSignal; after?: string | null },
) => AsyncIterable<SseFrame>

/** What `follow` needs from the screen around it. */
export interface FollowOptions {
    /** Every frame, in the order it arrived. */
    onFrame: (frame: SseFrame) => void
    /** Where the connection is, so the status bar can say it. */
    onState: (state: StreamState) => void
    /** The cursor to resume past, read fresh before each connect. */
    cursor: () => string | null
    /** Whether the run has settled, which is what makes an `end` frame the last word. */
    settled: () => boolean
    /** Stops the loop and aborts the connection it is holding. */
    signal: AbortSignal
    /** How a connection is opened. */
    open?: StreamSource
    /** How the loop waits between connections. */
    wait?: (ms: number) => Promise<void>
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

/**
 * Follow one run to its end, reconnecting while it is still going.
 *
 * Returns when the run has settled and the stream said so, or when the signal is aborted. An
 * `expired` frame reopens the stream after a short wait; every other ending -- a dropped
 * connection, a refusal, a stream that stopped mid-frame -- is a reconnect after a widening wait.
 */
export async function follow(runId: string, options: FollowOptions): Promise<void> {
    const open = options.open ?? streamSse
    const wait = options.wait ?? sleep
    const path = eventsPath(runId)
    let failures = 0

    while (!options.signal.aborted) {
        options.onState(failures === 0 ? 'connecting' : 'reconnecting')
        let ended = false
        let expired = false
        try {
            // One connection at a time: this loop is what the "one stream" rule is made of.
            // oxlint-disable-next-line no-await-in-loop
            for await (const frame of open(path, { signal: options.signal, after: options.cursor() })) {
                failures = 0
                options.onState('live')
                if (frame.event === 'expired') {
                    expired = true
                    break
                }
                options.onFrame(frame)
                if (frame.event === 'end') {
                    ended = true
                    break
                }
            }
        } catch {
            if (options.signal.aborted) return
            failures += 1
        }
        if (options.signal.aborted) return
        if (ended && options.settled()) {
            options.onState('ended')
            return
        }
        // oxlint-disable-next-line no-await-in-loop
        await wait(ended || expired ? CONTINUE_DELAY_MS : backoffFor(failures || 1))
    }
}
