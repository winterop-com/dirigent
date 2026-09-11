/**
 * Rendering the four machine values this app puts in front of people.
 *
 * A duration measured by the engine arrives as `duration_ms` and a size as `<thing>_bytes`, both
 * integers, because that is what the records carry; the reading is made here and nowhere else,
 * so a step's timing on the graph and the same timing in the panel cannot disagree.
 *
 * A URI is shortened rather than wrapped. A storage URI is a scheme, a bucket and a long key,
 * and the end of it is the part that says which object -- so the middle is what goes, and the
 * whole of it stays available as the element's title.
 *
 * WHICH CLOCK AN INSTANT IS READ AGAINST IS NOT DECIDED HERE. `lib/times` holds it, and every
 * function below that renders a wall-clock time asks it, so one setting moves every timestamp
 * in the app at once instead of each screen deciding for itself.
 */

import { currentZone, timesMode, zoneSuffix } from '@/lib/times'

/** How long something took, from the milliseconds the engine measured. */
export function formatDuration(durationMs: number | null | undefined): string {
    if (durationMs === null || durationMs === undefined) return '--'
    if (durationMs < 1000) return `${String(Math.max(0, Math.round(durationMs)))}ms`
    const seconds = durationMs / 1000
    if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`
    const minutes = Math.floor(seconds / 60)
    const rest = Math.round(seconds - minutes * 60)
    if (minutes < 60) return `${String(minutes)}m ${String(rest)}s`
    const hours = Math.floor(minutes / 60)
    return `${String(hours)}h ${String(minutes - hours * 60)}m`
}

/** How long between two instants, or nothing when it has not finished. */
export function elapsedBetween(
    started: string | null | undefined,
    finished: string | null | undefined,
): number | null {
    if (!started || !finished) return null
    const from = Date.parse(started)
    const to = Date.parse(finished)
    if (Number.isNaN(from) || Number.isNaN(to)) return null
    return to - from
}

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB']

/** A size, from the bytes the record counted. */
export function formatBytes(bytes: number | null | undefined): string {
    if (bytes === null || bytes === undefined) return '--'
    if (bytes < 1024) return `${String(Math.max(0, Math.round(bytes)))} B`
    let value = bytes
    let unit = 0
    while (value >= 1024 && unit < UNITS.length - 1) {
        value /= 1024
        unit += 1
    }
    return `${value.toFixed(value < 10 ? 1 : 0)} ${UNITS[unit]}`
}

/** How much of a uuid names it on screen. Enough to tell two rows of one listing apart. */
export const SHORT_ID_LENGTH = 8

/**
 * The part of an identifier that tells it from its neighbours.
 *
 * THE TAIL, NOT THE HEAD. Every id this API mints is a uuid version 7, whose leading digits are
 * the millisecond it was minted at -- so four pipelines applied in one command, or a fan-out
 * of runs started together, all share their first eight characters and none of them is named
 * by them. The trailing digits are the random half, and they are what a reader is scanning for.
 */
export function shortId(id: string): string {
    return id.slice(-SHORT_ID_LENGTH)
}

/**
 * A heading over rows, carrying how many there are where there are any.
 *
 * A COUNT OF NOTHING IS NOT A COUNT. The empty state under the heading already says there is
 * nothing there, so "Artifacts (0)" is the same fact twice, one of them as arithmetic.
 */
export function countedHeading(noun: string, count: number): string {
    return count === 0 ? noun : `${noun} (${String(count)})`
}

/**
 * Whether when a row was last written is a fact beside when it was created.
 *
 * A ROW NOBODY HAS EDITED CARRIES TWO INSTANTS a few microseconds apart, which is the write
 * itself and not an edit -- so "created 1m ago · updated 1m ago" is one fact said twice. What
 * makes the second worth drawing is reading differently from the first.
 */
export function separatelyUpdated(created: string, updated: string, now: number = Date.now()): boolean {
    return formatRelative(updated, now) !== formatRelative(created, now)
}

/** How much of a digest is shown, which is what `dg versions` prints in its own column. */
export const SHORT_DIGEST_LENGTH = 12

/**
 * A version's digest at the length two of them are told apart at.
 *
 * THE HEAD, WITHOUT THE ALGORITHM. A digest arrives as `sha256:` and sixty-four hex digits, and
 * every one of them names the same algorithm; what says which version this is starts after it.
 */
export function shortDigest(digest: string): string {
    return digest.slice(digest.indexOf(':') + 1, digest.indexOf(':') + 1 + SHORT_DIGEST_LENGTH)
}

/** How long a URI may be before its middle is dropped. */
const URI_BUDGET = 44

/**
 * A storage URI at a readable length, keeping the scheme and the end of the key.
 *
 * The tail is what says which object; the middle of a key is prefixes somebody chose once.
 */
export function shortenUri(uri: string, budget: number = URI_BUDGET): string {
    if (uri.length <= budget) return uri
    const separator = uri.indexOf('://')
    const head = separator === -1 ? '' : uri.slice(0, separator + 3)
    const rest = uri.slice(head.length)
    const room = Math.max(8, budget - head.length - 1)
    return `${head}…${rest.slice(rest.length - room)}`
}

/**
 * The fields an exact instant is written out of, largest first.
 *
 * `en-CA` is asked for rather than the reader's own locale because the parts are reassembled
 * here and the locale only decides how each one is spelled; `h23` is what keeps midnight at
 * `00` rather than `24`.
 */
const EXACT: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
}

/** The date alone, which is what a reading past the recency window says. */
const EXACT_DATE: Intl.DateTimeFormatOptions = { year: 'numeric', month: '2-digit', day: '2-digit' }

type InstantField = 'year' | 'month' | 'day' | 'hour' | 'minute' | 'second'

function partsOf(at: Date, shape: Intl.DateTimeFormatOptions): (field: InstantField) => string {
    const parts = new Intl.DateTimeFormat('en-CA', { ...shape, timeZone: currentZone() }).formatToParts(at)
    const held = new Map<string, string>(parts.map((part) => [part.type, part.value]))
    return (field) => held.get(field) ?? '00'
}

/** A day, largest field first: `2026-09-02`. */
function exactDate(at: Date): string {
    const part = partsOf(at, EXACT_DATE)
    return `${part('year')}-${part('month')}-${part('day')}`
}

/**
 * A wall-clock instant, written largest field first in the zone `lib/times` is set to.
 *
 * ONE SPELLING, NOT THE READER'S LOCALE. An instant is read here to be compared -- against a
 * log line, against another screen, against what a machine wrote -- and `9/2/2026, 11:36:05 AM`
 * sorts by nothing and means different days to different readers. Every exact instant in this
 * app is this shape, and it is the hover title under every relative reading.
 */
export function formatInstant(when: string | null | undefined): string {
    if (!when) return '--'
    const parsed = new Date(when)
    if (Number.isNaN(parsed.getTime())) return when
    const part = partsOf(parsed, EXACT)
    const exact = `${exactDate(parsed)} ${part('hour')}:${part('minute')}:${part('second')}`
    return exact + zoneSuffix(timesMode.get())
}

/** Where a relative reading stops being useful and a date says more. */
const RELATIVE_DAYS = 30

/**
 * How far from now something is, in the coarsest unit that still says it.
 *
 * A listing is read by how recent a row is rather than by the wall clock, so the coarse reading
 * is the one on screen and the instant itself is the element's title. Past a month, on either
 * side of now, there is no recency left to read and the date is what somebody wants.
 *
 * BOTH DIRECTIONS, ONE READING. When a schedule fires next is the same question as when a run
 * started, so the distance is measured the same way whichever side of now it falls on and only
 * the words around it change. The window either side of now is one instant: a clock a few
 * seconds out of step reads as "just now" rather than as a firing already overdue.
 */
export function formatRelative(when: string | null | undefined, now: number = Date.now()): string {
    if (!when) return '--'
    const at = Date.parse(when)
    if (Number.isNaN(at)) return when
    const signed = Math.round((now - at) / 1000)
    const seconds = Math.abs(signed)
    if (seconds < 45) return 'just now'
    const ahead = signed < 0
    const minutes = Math.round(seconds / 60)
    if (minutes < 60) return said(`${String(minutes)}m`, ahead)
    const hours = Math.round(minutes / 60)
    if (hours < 24) return said(`${String(hours)}h`, ahead)
    const days = Math.round(hours / 24)
    if (days <= RELATIVE_DAYS) return said(`${String(days)}d`, ahead)
    return exactDate(new Date(at))
}

/** How a span reads on the side of now it falls: `3m ago` behind it, `in 3m` ahead of it. */
function said(span: string, ahead: boolean): string {
    return ahead ? `in ${span}` : `${span} ago`
}

/** The fields a firing is read by: the weekday, the day, the month, and the clock. */
const MOMENT: Intl.DateTimeFormatOptions = {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
}

/**
 * A moment as a reading rather than a stamp: `Tue 8 Sep 05:00`.
 *
 * IT IS READ IN THE ZONE IT WAS DECLARED IN, not the one the app's clock is set to: what a
 * schedule promises is five in the morning where it fires, and drawing that against another
 * zone would answer a question nobody asked. A caller with no zone of its own passes none, and
 * the moment is read on the clock the app is set to like every other instant.
 *
 * The fields are assembled rather than formatted whole, because a locale writes a sentence
 * between them and this is four fields, largest first, like every other time in this app.
 */
export function formatMoment(when: string, zone: string | undefined): string {
    const at = new Date(when)
    if (Number.isNaN(at.getTime())) return when
    const held = new Map(
        new Intl.DateTimeFormat('en-US', { ...MOMENT, timeZone: zone })
            .formatToParts(at)
            .map((part) => [part.type, part.value]),
    )
    const field = (name: Intl.DateTimeFormatPartTypes) => held.get(name) ?? ''
    return `${field('weekday')} ${field('day')} ${field('month')} ${field('hour')}:${field('minute')}`
}

/**
 * The interval a run covers, as the pair of instants a query was filtered on.
 *
 * A WINDOW IS NOT READ BY RECENCY. Every other instant on a run answers how long ago it was, and
 * this one answers which data the run took: a step filtered `date.created` between these two, so
 * what somebody checks it against is a date on a source, not the distance from now. Both ends are
 * read on the clock the app is set to and the zone is stated once, after the pair.
 */
export function formatWindow(start: string, end: string): string {
    const zone = currentZone()
    return `${formatMoment(start, zone)} to ${formatMoment(end, zone)}${zoneSuffix(timesMode.get())}`
}

/** A clock time alone, which is what a log line carries beside its message. */
export function formatClock(when: string | null | undefined): string {
    if (!when) return '--'
    const parsed = new Date(when)
    if (Number.isNaN(parsed.getTime())) return when
    return parsed.toLocaleTimeString(undefined, { hour12: false, timeZone: currentZone() })
}

/** A JSON value as a read-only block: stable key order, two-space indent. */
export function asJson(value: unknown): string {
    return JSON.stringify(value, null, 2) ?? 'null'
}
