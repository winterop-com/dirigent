/**
 * What the screen in front of somebody has to say along the foot of the shell.
 *
 * The status bar is the shell's and is drawn once; what it says about the work is the screen's,
 * and a screen states it here for as long as it is mounted. Two facts fit: one short note on the
 * left of the version, and one identifier on the right, which is what a trace id is.
 *
 * The note is data rather than markup, so the decision "what does a connecting stream say" is a
 * pure function testable in Node, and the bar stays one row whatever it holds.
 */

import type { StreamState } from '@/lib/run-detail'
import { createStore } from '@/lib/store'

/** How loudly the note is drawn: a live stream is not a warning and must not read as one. */
export type StatusTone = 'live' | 'quiet' | 'warn'

/** One screen's two facts. */
export interface ScreenStatus {
    note: string | null
    tone: StatusTone
    /** A machine's string the bar sets in mono, such as a trace id. */
    identifier: string | null
}

const NOTHING: ScreenStatus = { note: null, tone: 'quiet', identifier: null }

export const screenStatus = createStore<ScreenStatus>(NOTHING)

/** Say what this screen is doing. Publishes nothing when it is saying the same thing again. */
export function setScreenStatus(next: ScreenStatus): void {
    const current = screenStatus.get()
    if (current.note === next.note && current.tone === next.tone && current.identifier === next.identifier) return
    screenStatus.set(next)
}

/** Say nothing, which is what the bar shows on a screen that states nothing. */
export function clearScreenStatus(): void {
    screenStatus.set(NOTHING)
}

/**
 * What one run's stream is doing, in the words the bar uses.
 *
 * The word is the state alone. How the events arrive is plumbing, and the bar says none of it.
 *
 * A SETTLED STREAM SAYS NOTHING. The note exists only while it is stateful; once the run has
 * settled the chip beside its name already says so, and a line restating it for as long as the
 * screen is open is a static note the bar is not for.
 */
export function streamNote(stream: StreamState): { note: string | null; tone: StatusTone } {
    switch (stream) {
        case 'connecting':
            return { note: 'connecting', tone: 'quiet' }
        case 'live':
            return { note: 'live', tone: 'live' }
        case 'reconnecting':
            return { note: 'reconnecting', tone: 'warn' }
        case 'ended':
            return { note: null, tone: 'quiet' }
    }
}
