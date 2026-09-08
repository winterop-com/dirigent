/**
 * The run terminal: where the drawer sits, and every decision about which lines it draws.
 *
 * THE LINES ARE THE RUN'S OWN STATE, NOT A SECOND READ. `runs/{id}/$events` already carries
 * every log line the run wrote, in the order it wrote them, and `lib/run-detail` holds them as
 * one list. The drawer filters that list; it opens no connection of its own, and the counter in
 * `run-stream.test.ts` is what makes that fail a test rather than a review.
 *
 * FILTERING IS CLIENT-SIDE HERE, AND THAT IS NOT THE LISTING RULE BEING BROKEN. A listing's
 * filter must be the server's because a listing is a window onto rows nobody has read. This is
 * the opposite case: every line the drawer can draw is already in memory, so narrowing them is
 * arithmetic over what is held rather than a question the server would have to answer again.
 *
 * PX-INTENT, THE SAME AS THE PANELS. What somebody dragged the drawer to was a decision about
 * how many lines they wanted to see at once, so it is kept in pixels and clamped for a short
 * window rather than re-decided as a fraction of one.
 */

import { formatClock } from '@/lib/format'
import type { RunDetailState } from '@/lib/run-detail'
import type { LogEntryOut } from '@/lib/runs'
import { runSettled, statusLabel, type LogLevel } from '@/lib/status'
import { createStore } from '@/lib/store'

/** Where the drawer opens when nobody has dragged it. Roughly a dozen lines and its header. */
export const TERMINAL_DEFAULT_HEIGHT = 280

/** Shorter than this and the header is the drawer, so a drag stops here. */
export const TERMINAL_MIN_HEIGHT = 140

/** Taller than this and the graph the drawer sits under stops being on screen. */
export const TERMINAL_MAX_HEIGHT = 720

const OPEN_KEY = 'dirigent.terminalOpen'
const HEIGHT_KEY = 'dirigent.terminalHeight'

function readFlag(key: string, fallback: boolean): boolean {
    try {
        const stored = localStorage.getItem(key)
        return stored === null ? fallback : stored === 'true'
    } catch {
        return fallback
    }
}

function readHeight(): number {
    try {
        const stored = Number(localStorage.getItem(HEIGHT_KEY))
        return Number.isFinite(stored) && stored > 0 ? clampTerminalHeight(stored) : TERMINAL_DEFAULT_HEIGHT
    } catch {
        return TERMINAL_DEFAULT_HEIGHT
    }
}

function write(key: string, value: string): void {
    try {
        localStorage.setItem(key, value)
    } catch {
        // Storage denied: the drawer holds for as long as this document is open.
    }
}

/** Hold a dragged height inside what the content area can actually draw. */
export function clampTerminalHeight(height: number): number {
    return Math.min(TERMINAL_MAX_HEIGHT, Math.max(TERMINAL_MIN_HEIGHT, Math.round(height)))
}

export const terminalOpen = createStore(readFlag(OPEN_KEY, false))
export const terminalHeight = createStore(readHeight())

/** Show or hide the drawer, and remember which for the next visit. */
export function toggleTerminal(): void {
    terminalOpen.update((open) => {
        write(OPEN_KEY, String(!open))
        return !open
    })
}

/** Set the drawer's height, in pixels, clamped to what the content area can draw. */
export function setTerminalHeight(height: number): void {
    const clamped = clampTerminalHeight(height)
    write(HEIGHT_KEY, String(clamped))
    terminalHeight.set(clamped)
}

/**
 * The levels, quietest first, which is the order a threshold is read against.
 *
 * `LogLevel` off the wire, in severity order rather than alphabetical: the index into this
 * array is what "at least this level" compares.
 */
export const LEVELS: readonly LogLevel[] = ['debug', 'info', 'warning', 'error']

/** What each threshold is called on the control, said as what it lets through. */
export const LEVEL_LABELS: Record<LogLevel, string> = {
    debug: 'All levels',
    info: 'Info and up',
    warning: 'Warnings and up',
    error: 'Errors only',
}

/** Whether a line's own level is at or above the threshold in front of the reader. */
export function atLeast(level: string, threshold: LogLevel): boolean {
    const found = LEVELS.indexOf(level as LogLevel)
    // A level this bundle was built before is shown rather than hidden: a line nobody can read
    // is worse than a line below the threshold.
    if (found === -1) return true
    return found >= LEVELS.indexOf(threshold)
}

/** What the three controls in the drawer's header row hold between them. */
export interface LineFilters {
    /** The quietest level drawn. `debug` is every line. */
    level: LogLevel
    /** One step's name, or the empty string for every step. */
    step: string
    /** What a line has to contain, matched without case. The empty string matches everything. */
    match: string
}

/** No narrowing at all, which is what the drawer opens on. */
export const EVERY_LINE: LineFilters = { level: 'debug', step: '', match: '' }

/** Whether anything has been asked of the drawer, which is what an empty state has to know. */
export function narrowed(filters: LineFilters): boolean {
    return filters.level !== 'debug' || filters.step !== '' || filters.match !== ''
}

/**
 * A line's fields, compactly, or nothing where a line carries none.
 *
 * A block writes fields beside its message -- a uri, a byte count, an exit code -- and they are
 * the half of a line that says which one it is. They are rendered `key=value` after the
 * message rather than as a block, because a terminal is lines.
 */
export function fieldsText(fields: Record<string, unknown> | null | undefined): string | null {
    if (fields === null || fields === undefined) return null
    const pairs = Object.entries(fields).map(
        ([key, value]) => `${key}=${typeof value === 'string' ? value : (JSON.stringify(value) ?? 'null')}`,
    )
    return pairs.length === 0 ? null : pairs.join(' ')
}

/**
 * Everything one line is matched against: its item, its step, its message, and its fields.
 *
 * A MATCH IS OVER WHAT THE LINE DRAWS. The item label is joined on by the pane rather than
 * carried on the entry, so a search that did not know it would answer "no lines" about a label
 * the reader is looking straight at.
 */
function haystack(entry: LogEntryOut, labels: ReadonlyMap<string, string>): string {
    const item = entry.step_attempt_id === null ? undefined : labels.get(entry.step_attempt_id)
    return [item ?? '', entry.step_name ?? '', entry.message, fieldsText(entry.fields) ?? '']
        .join(' ')
        .toLowerCase()
}

/**
 * The lines the drawer draws, in the order the run wrote them.
 *
 * THE ORDER IS ARRIVAL ORDER AND NOTHING ELSE. Every step's lines are interleaved as the run
 * produced them, because the question the drawer answers -- what happened to this run -- is a
 * question about a sequence. Grouping by step would answer a different one, and the step select
 * is there for whoever is asking that instead.
 *
 * THE THREE CONTROLS COMPOSE. A level threshold, a step, and a match are three predicates over
 * one list, and all three hold at once.
 */
export function visibleLines(
    logs: readonly LogEntryOut[],
    filters: LineFilters,
    labels: ReadonlyMap<string, string>,
): LogEntryOut[] {
    const wanted = filters.match.trim().toLowerCase()
    return logs.filter((entry) => {
        if (!atLeast(entry.level, filters.level)) return false
        if (filters.step !== '' && entry.step_name !== filters.step) return false
        return wanted === '' || haystack(entry, labels).includes(wanted)
    })
}

/**
 * How many lines one entry draws.
 *
 * AN ENTRY IS NOT A LINE. A block writes what it wrote, and a message carrying newlines is
 * drawn as the several lines it is -- the pane is `whitespace-pre-wrap`, so nothing folds them
 * away. Counting entries would tell somebody scrolling two hundred lines that there are
 * forty-two of them.
 */
export function lineSpan(entry: LogEntryOut): number {
    const fields = fieldsText(entry.fields)
    const drawn = fields === null ? entry.message : `${entry.message} ${fields}`
    return drawn.split('\n').length
}

/** How many lines a set of entries draws between them. */
export function countLines(entries: readonly LogEntryOut[]): number {
    return entries.reduce((total, entry) => total + lineSpan(entry), 0)
}

/**
 * What the count line says: how many lines are on screen out of how many the run has written,
 * or nothing at all where the run has written none.
 *
 * "0 OF 0 LINES" IS AN EMPTY STATE IN ARITHMETIC. The pane below already says nothing was
 * logged, so the count has a fact only once there is a line to count.
 */
export function lineCount(shown: number, total: number): string | null {
    if (total === 0) return null
    const lines = total === 1 ? 'line' : 'lines'
    return `${String(shown)} of ${String(total)} ${lines}`
}

/**
 * What the drawer says when it has nothing to draw, which depends on why it has nothing.
 *
 * "Nothing logged yet" in front of somebody who filtered to errors is a lie about the run, so a
 * narrowed drawer says what would widen it instead.
 */
/**
 * What the last line of the console says once no more lines are coming.
 *
 * The outcome is the answer to "is anything still coming", so the line states it in the run's
 * own state word. A console opened on a run this screen has not read states the end alone.
 */
export function endNote(status: string | null): string {
    if (status === null || !runSettled(status)) return 'end of log'
    return `run ${statusLabel(status)}`
}

export function emptyNote(filters: LineFilters, total: number, settled = false): string {
    if (total > 0 || narrowed(filters)) return 'No line matches these filters.'
    if (settled) return 'This run logged nothing.'
    return 'Nothing logged.'
}

/**
 * The steps the step select offers: every node of the run's graph, in the order it was laid out.
 *
 * The graph rather than the lines already held, because a step that has written nothing is
 * still a step somebody may be looking for -- and a select whose rows appear as a run goes is a
 * control that moves under the pointer.
 */
export function stepChoices(state: RunDetailState): string[] {
    return state.dag.nodes.map((node) => node.code)
}

/**
 * Which step a line's prefix opens, or nothing where no step wrote it.
 *
 * A run-level line -- the engine's own, an alert's -- carries no step, so its prefix is a label
 * rather than a control. Nothing wears interactive chrome unless it does something.
 */
export function stepOf(entry: LogEntryOut): string | null {
    return entry.step_name === null || entry.step_name === '' ? null : entry.step_name
}

/** One line as text, which is what the copy button puts on the clipboard. */
export function lineText(entry: LogEntryOut): string {
    const fields = fieldsText(entry.fields)
    return [
        formatClock(entry.created_at),
        entry.level,
        entry.step_name ?? '-',
        entry.message,
        ...(fields === null ? [] : [fields]),
    ].join(' ')
}

/** The lines on screen, as the text a paste into an issue or a chat should read as. */
export function copyText(entries: readonly LogEntryOut[]): string {
    return entries.map((entry) => lineText(entry)).join('\n')
}

/** A run's log as NDJSON: one entry per line, exactly as the API answered it. */
export function asNdjson(entries: readonly LogEntryOut[]): string {
    return entries.map((entry) => JSON.stringify(entry)).join('\n')
}

/** What the file a download saves is called. */
export function downloadName(runId: string): string {
    return `dirigent-run-${runId}.ndjson`
}
