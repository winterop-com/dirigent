/**
 * The window an ad hoc run may carry, and whether the document it runs needs one.
 *
 * A WINDOW IS A FACT ABOUT A RUN, NOT ABOUT A PIPELINE. A schedule-fired run covers a logical
 * data interval and its steps read `${run.window.start}` and `${run.window.end}`; a run started
 * by hand carries one only where somebody gave it one, and a step reading an edge of a window
 * the run has not got stops the run at that step. So a document that references either edge is
 * one the dialog asks for a window before it will start, and every other document is offered
 * the two boxes and asked nothing.
 *
 * A `datetime-local` BOX HAS NO ZONE AND THE WIRE NEEDS ONE. What somebody types is a wall
 * clock, and which clock it is read against is the app's own setting, so the offset is passed
 * in from `lib/times` rather than taken from the machine here -- which is what keeps every
 * decision below a pure function a Node test can run.
 */

import type { JsonMap } from '@/lib/api'

/** What a step writes to read an edge of its run's window. */
const WINDOW_REFERENCE = 'run.window'

/** Why Run is shut on a document whose steps read a window nothing has given them. */
export const WINDOW_NEEDED = 'This pipeline needs a window'

/** Why Run is shut on one end of a window given without the other. */
export const WINDOW_HALF = 'A window has two ends: give both, or neither.'

/** Why Run is shut on a window that does not run forwards. */
export const WINDOW_BACKWARDS = 'A window runs forwards: the start is before the end.'

/** What a `datetime-local` box holds: a wall clock to the minute, with no zone on it. */
const LOCAL_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/

/**
 * Whether anything in a document reads an edge of the run's window.
 *
 * THE WHOLE DOCUMENT, NOT THE STEPS' CONFIG ALONE. A reference is a string wherever it is
 * written -- a nested config value, an element of a list, a `for_each` expression, a step's own
 * `when` -- so the walk is over every string the document holds and the key it sits under
 * decides nothing.
 */
export function referencesWindow(document: JsonMap | null): boolean {
    return holdsReference(document)
}

function holdsReference(value: unknown): boolean {
    if (typeof value === 'string') return value.includes(WINDOW_REFERENCE)
    if (Array.isArray(value)) return value.some(holdsReference)
    if (value !== null && typeof value === 'object') return Object.values(value).some(holdsReference)
    return false
}

/**
 * The instant a box holds, written in ISO 8601 with the zone the app reads clocks against.
 *
 * A box that is empty or half typed is no instant at all, which is what shuts the button rather
 * than what is sent as a broken one.
 */
export function windowInstant(written: string, offsetMinutes: number): string | null {
    if (!LOCAL_INSTANT.test(written)) return null
    return `${written}:00${zoneSuffix(offsetMinutes)}`
}

/** The zone an offset in minutes is written as: `Z`, `+02:00`, `-05:30`. */
function zoneSuffix(offsetMinutes: number): string {
    if (offsetMinutes === 0) return 'Z'
    const sign = offsetMinutes < 0 ? '-' : '+'
    const total = Math.abs(offsetMinutes)
    return `${sign}${pad(Math.floor(total / 60))}:${pad(total % 60)}`
}

/**
 * One instant off the wire as the box would hold it, on the clock the app is set to.
 *
 * This is what pre-fills a re-run: the window the finished run carried, read back on the same
 * clock every other instant on that screen is read on.
 */
export function windowBox(instant: string | null | undefined, offsetMinutes: number): string {
    if (!instant) return ''
    const at = Date.parse(instant)
    if (Number.isNaN(at)) return ''
    const shifted = new Date(at + offsetMinutes * 60_000)
    return `${shifted.toISOString().slice(0, 10)}T${pad(shifted.getUTCHours())}:${pad(shifted.getUTCMinutes())}`
}

function pad(value: number): string {
    return String(value).padStart(2, '0')
}

/** A window as `RunRequest` carries it, both ends in ISO 8601 with their zone. */
export interface RunWindow {
    window_start: string
    window_end: string
}

/** What the two boxes amount to: a window, no window, or why no run can start from them. */
export type WindowReading = { kind: 'none' } | { kind: 'window'; window: RunWindow } | { kind: 'unready'; why: string }

/**
 * Read the two boxes as the window a run would carry.
 *
 * A HALF-GIVEN WINDOW IS NOT A WINDOW. `RunRequest` refuses one end without the other and
 * refuses a window that does not run forwards, so both are said here with the button still
 * unpressed. A document that reads a window is refused the empty pair as well, which is the one
 * case where giving nothing is not an option.
 *
 * EACH END IS OFFERED ITS OWN OFFSET, because a local clock's distance from UTC moves with
 * daylight saving and a window is free to run across the night it moves on.
 */
export function readWindow(
    start: string,
    end: string,
    needed: boolean,
    offsetAt: (written: string) => number,
): WindowReading {
    const from = windowInstant(start, offsetAt(start))
    const to = windowInstant(end, offsetAt(end))
    if (from === null || to === null) {
        if (from === null && to === null) return needed ? { kind: 'unready', why: WINDOW_NEEDED } : { kind: 'none' }
        return { kind: 'unready', why: needed ? WINDOW_NEEDED : WINDOW_HALF }
    }
    if (Date.parse(from) >= Date.parse(to)) {
        return { kind: 'unready', why: needed ? WINDOW_NEEDED : WINDOW_BACKWARDS }
    }
    return { kind: 'window', window: { window_start: from, window_end: to } }
}
