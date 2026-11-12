/**
 * One open run, as a state and a reducer over the frames its event stream carries.
 *
 * WHY A REDUCER AND NOT A PILE OF `useState`. A run's screen is fed by one multiplexed stream
 * that replays every attempt on connect, reconnects after a drop, and may deliver a state the
 * screen has already seen or an older state than the one it holds. The rules that make that
 * safe -- dedupe a replayed attempt by its own id, never let an older frame move a settled
 * state backwards, resume the log at the last id the stream stated -- are the correctness of
 * this screen, and none of them are testable inside a component. They are a pure function here
 * instead, and the screen is what draws its result.
 *
 * `applyFrame` RETURNS THE STATE IT WAS GIVEN when a frame changes nothing. That is what makes
 * the connect replay idempotent by `Object.is` rather than merely equal: a reconnect that
 * repeats forty attempt frames re-renders nothing.
 *
 * ONLY A LOG FRAME CARRIES AN ID. The server replays attempt and run frames on every connect
 * and deliberately gives them no id, so the log cursor is the only position a reconnect can
 * restore; `resumeCursor` is that position and nothing else may be used as one.
 */

import type { RunStep } from '@winterop-com/sokkel-ui-graph/RunGraph'
import { elapsedBetween, formatDuration } from '@/lib/format'
import { ICONS } from '@/lib/icons'
import { headingOf } from '@/lib/identity'
import { counted, LABELS } from '@/lib/labels'
import type { SseFrame } from '@/lib/sse'
import {
    attemptSettled,
    runSettled,
    type AnyStatus,
    type AttemptStatus,
    type StepOutcome,
} from '@/lib/status'
import {
    replySent,
    type AttemptEvent,
    type DagNode,
    type DagView,
    type LogEntryOut,
    type RunDetailOut,
    type RunOut,
} from '@/lib/runs'

/** How much of a run's log this screen holds. A tail is a tail; the API pages the whole of it. */
export const MAX_LOG_LINES = 5000

/** How many fan-out elements a node draws individually before it draws counts instead. */
export const ITEM_STRIP_LIMIT = 6

/** Where the one event stream is. */
export type StreamState = 'connecting' | 'live' | 'reconnecting' | 'ended'

/** Everything one open run's screen draws, and nothing about how it is drawn. */
export interface RunDetailState {
    run: RunOut
    dag: DagView
    /** Every attempt this stream has reported, by its own id, which is how a replay dedupes. */
    attempts: Readonly<Record<string, AttemptEvent>>
    /** The attempt ids in the order they were first seen, so a step's attempts have an order. */
    order: readonly string[]
    /** The run's whole log tail, oldest first, capped at `MAX_LOG_LINES`. */
    logs: readonly LogEntryOut[]
    /** The highest log id applied, which is the only cursor a reconnect may resume past. */
    lastLogId: number | null
    stream: StreamState
    /** The tags this queued run needs that no live worker carried when the run was read. */
    waitingForWorkers: readonly string[] | null
}

/** One frame of the run's story, named by the discriminator this app owns. */
export type RunFrame =
    | { kind: 'attempt'; attempt: AttemptEvent }
    | { kind: 'log'; entry: LogEntryOut }
    | { kind: 'run'; run: RunOut }
    | { kind: 'end' }
    | { kind: 'unknown'; event: string }

/** The state one initial read lands in, before the stream has said anything. */
export function initialState(detail: RunDetailOut): RunDetailState {
    return {
        run: detail.run,
        dag: detail.dag,
        attempts: {},
        order: [],
        logs: [],
        lastLogId: null,
        stream: 'connecting',
        waitingForWorkers: detail.waiting_for_workers,
    }
}

/**
 * Read one SSE frame as the thing it says it is.
 *
 * A frame whose payload does not parse is not a crash: the stream is long-lived and one bad
 * line must not take the screen down with it, so it becomes an unknown frame the reducer drops.
 */
export function decodeFrame(frame: SseFrame): RunFrame {
    if (frame.event === 'end') return { kind: 'end' }
    let payload: unknown
    try {
        payload = JSON.parse(frame.data)
    } catch {
        return { kind: 'unknown', event: frame.event }
    }
    if (payload === null || typeof payload !== 'object') return { kind: 'unknown', event: frame.event }
    if (frame.event === 'attempt') return { kind: 'attempt', attempt: payload as AttemptEvent }
    if (frame.event === 'log') return { kind: 'log', entry: payload as LogEntryOut }
    if (frame.event === 'run') return { kind: 'run', run: payload as RunOut }
    return { kind: 'unknown', event: frame.event }
}

/** The observable part of an attempt: a change to any of it is news. */
function attemptFingerprint(attempt: AttemptEvent): string {
    return [
        attempt.status,
        String(attempt.attempt),
        attempt.finished_at ?? '',
        attempt.waiting_message ?? '',
        String(attempt.waiting_progress ?? ''),
        attempt.error ?? '',
        attempt.output_uri ?? '',
    ].join(' ')
}

/** The observable part of a run. */
function runFingerprint(run: RunOut): string {
    return [run.status, run.started_at ?? '', run.finished_at ?? '', run.error ?? ''].join(' ')
}

/**
 * Fold one frame into the state.
 *
 * The state itself comes back when the frame said nothing new, which is what makes a replay
 * free. Two frames are refused outright: an attempt that would move a settled attempt back to a
 * live one, and a run frame that would move a settled run back to a live one. Both are what an
 * out-of-order delivery or a stale replay looks like, and neither is news.
 */
export function applyFrame(state: RunDetailState, frame: RunFrame): RunDetailState {
    switch (frame.kind) {
        case 'attempt': {
            const incoming = frame.attempt
            const held = state.attempts[incoming.id]
            if (held !== undefined) {
                if (attemptFingerprint(held) === attemptFingerprint(incoming)) return state
                if (attemptSettled(held.status) && !attemptSettled(incoming.status)) return state
                if (incoming.attempt < held.attempt) return state
            }
            return {
                ...state,
                attempts: { ...state.attempts, [incoming.id]: incoming },
                order: held === undefined ? [...state.order, incoming.id] : state.order,
            }
        }
        case 'log': {
            const entry = frame.entry
            if (state.lastLogId !== null && entry.id <= state.lastLogId) return state
            const grown = [...state.logs, entry]
            return {
                ...state,
                logs: grown.length > MAX_LOG_LINES ? grown.slice(grown.length - MAX_LOG_LINES) : grown,
                lastLogId: entry.id,
            }
        }
        case 'run': {
            if (runFingerprint(state.run) === runFingerprint(frame.run)) return state
            if (runSettled(state.run.status) && !runSettled(frame.run.status)) return state
            return { ...state, run: frame.run }
        }
        case 'end':
            return state.stream === 'ended' ? state : { ...state, stream: 'ended' }
        case 'unknown':
            return state
    }
}

/** What can happen to a run's screen: another run was opened, its read landed, a frame arrived, the stream moved. */
export type RunAction =
    | { kind: 'reset' }
    | { kind: 'loaded'; detail: RunDetailOut }
    | { kind: 'frame'; frame: RunFrame }
    | { kind: 'stream'; stream: StreamState }

/**
 * The whole of the screen's state, including not having read the run yet.
 *
 * A frame that arrives before the initial read is dropped rather than queued: the stream is
 * only opened once the read has landed, so there is no such frame to keep.
 *
 * OPENING ANOTHER RUN EMPTIES THIS STATE FIRST. Everything held here belongs to one run -- the
 * attempts, the log tail and the cursor `resumeCursor` hands a reconnect -- so a screen that
 * moved to another run and kept them would resume the new run's stream past the old run's last
 * log id and skip everything below it.
 */
export function reduce(state: RunDetailState | null, action: RunAction): RunDetailState | null {
    if (action.kind === 'reset') return null
    if (action.kind === 'loaded') return initialState(action.detail)
    if (state === null) return null
    if (action.kind === 'frame') return applyFrame(state, action.frame)
    return withStream(state, action.stream)
}

/** Say where the stream is, without disturbing anything it has already delivered. */
export function withStream(state: RunDetailState, stream: StreamState): RunDetailState {
    return state.stream === stream ? state : { ...state, stream }
}

/** The cursor a reconnect resumes past, which is the last log id and never an attempt's. */
export function resumeCursor(state: RunDetailState): string | null {
    return state.lastLogId === null ? null : String(state.lastLogId)
}

/** The entries one step wrote, which is how a step's log pane is filled from the one stream. */
export function logsForStep(logs: readonly LogEntryOut[], step: string): LogEntryOut[] {
    return logs.filter((entry) => entry.step_name === step)
}

/** Every attempt of one step, oldest first. */
export function attemptsForStep(state: RunDetailState, step: string): AttemptEvent[] {
    return state.order
        .map((id) => state.attempts[id])
        .filter((attempt): attempt is AttemptEvent => attempt !== undefined && attempt.step_name === step)
}

/**
 * The item label each attempt ran for, keyed by the attempt's own id.
 *
 * A LOG LINE NAMES ITS ITEM FROM WHAT THE SCREEN ALREADY HOLDS. `LogEntryOut` carries the
 * attempt that wrote the line and no label of its own, and the attempts are already on the same
 * stream carrying theirs, so the join is here rather than a second field on every line. An
 * attempt of a step that does not fan out is not in this map, and its lines carry no label.
 */
export function itemLabels(state: RunDetailState): Map<string, string> {
    const labels = new Map<string, string>()
    for (const id of state.order) {
        const attempt = state.attempts[id]
        if (attempt !== undefined && attempt.item !== null && attempt.item !== '')
            labels.set(attempt.id, attempt.item)
    }
    return labels
}

/** The fan-out element one log line was written for, or nothing where it was written for none. */
export function itemOfEntry(labels: ReadonlyMap<string, string>, attemptId: string | null): string | null {
    return attemptId === null ? null : (labels.get(attemptId) ?? null)
}

/** The attempt that speaks for one fan-out element, or for the step when it does not fan out. */
function latestOf(attempts: readonly AttemptEvent[]): AttemptEvent | null {
    return attempts.reduce<AttemptEvent | null>(
        (best, attempt) => (best === null || attempt.attempt >= best.attempt ? attempt : best),
        null,
    )
}

/** The latest attempt per fan-out element, keyed by the element's own id. */
function latestPerItem(attempts: readonly AttemptEvent[]): Map<string, AttemptEvent> {
    return new Map(itemTries(attempts).map((item) => [item.id, item.latest]))
}

/**
 * One fan-out element of a step: every try it has had, newest first.
 *
 * THE ELEMENT IS `run_item_id`, AND THE ORDER IS `item_index`. `item` is a label and not an
 * identity: two elements of one fan-out may carry the same input value, or values that truncate
 * to the same label, and grouping by it would fold them into one -- a step reading as succeeded
 * while another element is still running or has failed. The index is where the element sits in
 * the list the step was mapped over, which is the order the engine expands them in and the order
 * the document wrote them in. A step that does not fan out is one group under its own name.
 */
export interface ItemTries {
    /** The element's own id, or the step's name where the step does not fan out. */
    id: string
    /** The label the element is known by, or the step's name where there is no element. */
    key: string
    index: number | null
    /** Every try of this element, newest first, which is never empty. */
    tries: AttemptEvent[]
    /** The newest try, which is what the element amounts to now. */
    latest: AttemptEvent
}

/** Every try of one step, grouped by element, the groups in fan-out order and the tries newest first. */
export function itemTries(attempts: readonly AttemptEvent[]): ItemTries[] {
    const groups = new Map<string, AttemptEvent[]>()
    for (const attempt of attempts) {
        const key = attempt.run_item_id ?? attempt.step_name
        groups.set(key, [...(groups.get(key) ?? []), attempt])
    }
    const built: ItemTries[] = []
    for (const [id, group] of groups) {
        const tries = group.toSorted((left, right) => right.attempt - left.attempt)
        const latest = tries[0]
        if (latest === undefined) continue
        built.push({ id, key: latest.item ?? latest.step_name, index: latest.item_index, tries, latest })
    }
    // Stable, so elements the wire gave no index keep the order they were first seen in.
    return built.toSorted((left, right) => (left.index ?? 0) - (right.index ?? 0))
}

/**
 * Every try a step has had, in the order its panel lists them.
 *
 * FAN-OUT ORDER ACROSS ELEMENTS, NEWEST TRY WITHIN ONE. The elements are the list the step was
 * mapped over and read in the order that list was written; the tries of one element are a
 * history, and what happened last is the question in front of somebody reading it.
 */
export function attemptOrder(attempts: readonly AttemptEvent[]): AttemptEvent[] {
    return itemTries(attempts).flatMap((item) => item.tries)
}

/**
 * What each fan-out element contributed to the step's output.
 *
 * A FAN-OUT STEP'S OUTPUT IS THE LIST OF ITS ELEMENTS' OUTPUTS, in item order, and only the
 * elements that succeeded are in it. So an element with nothing here is absent from that list
 * rather than a null in it, and `status` is what says why -- which is the difference between a
 * batch the next step reads short and one it has not been handed yet.
 */
export interface ItemOutput {
    id: string
    key: string
    /** The state the element settled in, which is why it is or is not in the list. */
    status: AttemptStatus
    /** The try that produced the element's output, or nothing where it produced none. */
    produced: AttemptEvent | null
}

/** Each element's output, in item order, which is the list the step after this one reads. */
export function itemOutputs(attempts: readonly AttemptEvent[]): ItemOutput[] {
    return itemTries(attempts).map((item) => ({
        id: item.id,
        key: item.key,
        status: item.latest.status,
        produced: item.tries.find((one) => one.output !== null || one.output_uri !== null) ?? null,
    }))
}

/** The keys a block wraps its result in, which are the envelope and not the result. */
const ENVELOPE_KEYS: ReadonlySet<string> = new Set(['value', 'output_uri', 'output_bytes'])

/** One attempt's output as it is read: the value it produced, or where that value was written. */
export interface OutputReading {
    /** The value itself, when the output is inline. Null when it went to storage. */
    value: unknown
    /** Where the output was written, when it was. */
    uri: string | null
    /** How large it is there. */
    bytes: number | null
}

/**
 * What an attempt produced, with the envelope taken off.
 *
 * A block answers with `value`, `output_uri` and `output_bytes` together, so an inline result
 * arrives beside two nulls that say nothing about it. What somebody reading a step asks for is
 * the value; the URI and the size are the answer only where the output went to storage, which
 * is either the block writing it there itself or the engine spilling it.
 */
export function outputReading(
    attempt: Pick<AttemptEvent, 'output' | 'output_uri' | 'output_bytes'>,
): OutputReading {
    const map = attempt.output
    const wrapped =
        map !== null && 'output_uri' in map && Object.keys(map).every((key) => ENVELOPE_KEYS.has(key))
            ? map
            : null
    const inner = wrapped?.output_uri
    const uri = attempt.output_uri ?? (typeof inner === 'string' ? inner : null)
    if (uri !== null) {
        const size = wrapped?.output_bytes
        return { value: null, uri, bytes: attempt.output_bytes ?? (typeof size === 'number' ? size : null) }
    }
    return { value: wrapped === null ? map : (wrapped.value ?? null), uri: null, bytes: null }
}

const LIVE: ReadonlySet<AttemptStatus> = new Set<AttemptStatus>(['queued', 'running', 'waiting'])

/**
 * What a step amounts to, folded from the states its attempts are in.
 *
 * The order is what an operator wants to see first. Anything still moving makes the step
 * running, even beside an element that has already failed -- the step is not failed until
 * there is nothing left that could still succeed. A step every element skipped is skipped, and
 * a step with attempts left to start is running rather than pending.
 */
export function outcomeOf(attempts: readonly AttemptEvent[], fallback: string): StepOutcome {
    const latest = [...latestPerItem(attempts).values()]
    if (latest.length === 0) return fallback as StepOutcome
    const states = latest.map((attempt) => attempt.status)
    if (states.some((status) => LIVE.has(status))) return 'running'
    if (states.some((status) => status === 'pending')) {
        return states.every((status) => status === 'pending') ? 'pending' : 'running'
    }
    if (states.includes('failed')) return 'failed'
    if (states.includes('cancelled')) return 'cancelled'
    if (states.every((status) => status === 'skipped')) return 'skipped'
    return 'succeeded'
}

/** One fan-out element as its node draws it. */
export interface ItemChip {
    /** The element's own id, which is what tells two elements sharing a label apart. */
    id: string
    /** The label the item is known by: its key, or its index when it has no key. */
    key: string
    status: AttemptStatus
    /** The retry story, when this element is on a later try. */
    retry: string | null
}

/** How many elements are in each state, for a fan-out too wide to draw one by one. */
export interface ItemCount {
    status: AttemptStatus
    count: number
}

/** What a fan-out node shows inside itself: the elements, or how many are in each state. */
export type ItemStrip =
    | { kind: 'chips'; items: ItemChip[] }
    | { kind: 'counts'; counts: ItemCount[]; total: number }
    | { kind: 'empty' }

/**
 * One element's retry story, compactly.
 *
 * A first try has no story. A later one says which try it is, and when the next poll is due it
 * says how long that is -- which is the question somebody watching a retrying step is asking.
 */
export function retryStory(attempt: AttemptEvent, now: number): string | null {
    if (attempt.attempt <= 1) return null
    const due = attempt.next_poll_at === null ? Number.NaN : Date.parse(attempt.next_poll_at)
    if (Number.isNaN(due) || due <= now) return LABELS.runs.retry_try(String(attempt.attempt))
    return LABELS.runs.retry_try_in(String(attempt.attempt), String(Math.round((due - now) / 1000)))
}

/**
 * What a fan-out step draws inside its one node.
 *
 * A FAN-OUT IS ONE NODE, NEVER MANY. Sixty items are sixty attempts, not sixty boxes on a
 * graph, so past `limit` elements the strip stops naming them and starts counting them. The
 * threshold is a property of what fits in a node, which is why it is a number here rather than
 * a decision each caller makes.
 */
export function itemStrip(
    attempts: readonly AttemptEvent[],
    now: number,
    limit: number = ITEM_STRIP_LIMIT,
): ItemStrip {
    const latest = [...latestPerItem(attempts).entries()]
    if (latest.length === 0) return { kind: 'empty' }
    if (latest.length <= limit) {
        return {
            kind: 'chips',
            items: latest.map(([id, attempt]) => ({
                id,
                key: attempt.item ?? attempt.step_name,
                status: attempt.status,
                retry: retryStory(attempt, now),
            })),
        }
    }
    const tally = new Map<AttemptStatus, number>()
    for (const [, attempt] of latest) tally.set(attempt.status, (tally.get(attempt.status) ?? 0) + 1)
    return {
        kind: 'counts',
        counts: [...tally.entries()].map(([status, count]) => ({ status, count })),
        total: latest.length,
    }
}

/**
 * A step's attempts, with a late grid's gate left out once its items exist.
 *
 * A FAN-OUT OVER A STEP'S OUTPUT STARTS AS ONE ATTEMPT WITH NO ITEM, its gate, and the engine
 * deletes that attempt in the transaction that writes the items. The stream reports the items
 * and never the deletion, so the screen still holds the gate as pending: an item seen is what
 * says the gate is gone. Until then the gate is the step -- pending, or the reason the grid
 * could not be expanded -- and it is never an element of the step.
 */
export function stepAttempts(node: DagNode, attempts: readonly AttemptEvent[]): AttemptEvent[] {
    if (!node.fan_out) return [...attempts]
    const items = attempts.filter((attempt) => attempt.run_item_id !== null)
    return items.length > 0 ? items : [...attempts]
}

/** The elements of a fan-out step, which a gate standing in for them is not. */
function elementsOf(attempts: readonly AttemptEvent[]): AttemptEvent[] {
    return attempts.filter((attempt) => attempt.run_item_id !== null)
}

/** How many elements a fan-out step has: what the read counted, or what the stream has shown since. */
export function itemsTotal(node: DagNode, attempts: readonly AttemptEvent[]): number {
    const seen = new Set(elementsOf(attempts).map((attempt) => attempt.run_item_id))
    return Math.max(node.items_total, seen.size)
}

/**
 * What a fan-out node says where its elements would be, while it has none to draw.
 *
 * A LATE GRID NAMES WHAT IT WAITS FOR. Its width is whatever that step lists, so until the grid
 * expands the useful thing to say is which step that is; a grid fixed at creation, or one that
 * settled without expanding, only says that it fans out.
 */
export function emptyStripLabel(view: Pick<StepView, 'node' | 'outcome'>): string {
    const source = view.node.grid_source
    return source !== null && view.outcome === 'pending'
        ? LABELS.runs.waits_for(source)
        : LABELS.runs.fans_out
}

/** One node of the graph, folded from the pinned definition and everything the stream said. */
export interface StepView {
    node: DagNode
    outcome: StepOutcome
    /** The step's attempts, with a late grid's gate left out once its items exist. */
    attempts: AttemptEvent[]
    /** How many elements a fan-out step has, counted live as a late grid expands. */
    items: number
    latest: AttemptEvent | null
    /** The third line: what the step is waiting on, or what its last try had to say. */
    detail: string | null
    /** How long the step has taken, or nothing while it has not started. */
    duration_ms: number | null
    /** How long it sat between being written down and a worker taking it up. */
    queued_ms: number | null
    /** How long it sat parked between probes, which is a sensor's or a remote job's wait. */
    waiting_ms: number | null
    /** How far a live wait has come, from 0 to 1, or nothing when no live attempt reports it. */
    progress: number | null
    strip: ItemStrip
}

/**
 * What a step's third line says, which is the news rather than the state.
 *
 * A STEP WHOSE ITEMS GO ONE BY ONE SAYS SO WHILE THEY WAIT. Each of its items waits for its own
 * match rather than the whole of what it depends on, which is what the step is waiting on for as
 * long as its newest attempt is pending; an item running, parked or settled is the news instead.
 */
function detailOf(latest: AttemptEvent | null, node: DagNode): string | null {
    if (node.item_wise_parent !== null && (latest === null || latest.status === 'pending'))
        return LABELS.runs.item_by_item_after(node.item_wise_parent)
    if (latest === null)
        return node.depends_on.length === 0 ? null : LABELS.runs.depends_on_note(node.depends_on.join(', '))
    if (latest.waiting_message !== null && latest.waiting_message !== '') return latest.waiting_message
    if (latest.status === 'failed' && latest.error !== null) return latest.error
    if (latest.output_uri !== null) return LABELS.runs.saves_to(latest.output_uri)
    return null
}

/** The states in which an attempt's reported progress is still the news. */
const PROGRESSING: ReadonlySet<AttemptStatus> = new Set<AttemptStatus>(['running', 'waiting'])

/**
 * How far an attempt's wait has come, from 0 to 1, while the attempt is live.
 *
 * A SETTLED ATTEMPT HAS NO PROGRESS. The engine clears the fraction only on success, so a try that
 * failed, timed out or was cancelled still carries the last one it reported.
 */
export function progressOf(attempt: AttemptEvent | null): number | null {
    if (attempt === null || !PROGRESSING.has(attempt.status)) return null
    const fraction = attempt.waiting_progress
    if (fraction === null || !Number.isFinite(fraction)) return null
    return Math.min(1, Math.max(0, fraction))
}

/**
 * How long a step took: the earliest try to start until the latest one to finish.
 *
 * THE SPAN THE RUN REPORT MEASURES, so the graph, the step panel and the report say one number
 * about one step. Earliest and latest rather than first and last on the stream: a fan-out's
 * elements are claimed by whichever workers are free and settle in whatever order they settle,
 * so arrival order is not clock order, and reading it as one under-reports the step.
 *
 * A STEP IN FLIGHT IS COUNTED AGAINST THE CLOCK THE SCREEN ALREADY HOLDS. The run's screen ticks
 * `now` for as long as the run is live, which is what a retry's countdown is drawn from, so a
 * running step says how long it has been running without a second timer anywhere. A step that
 * has not started says nothing, and neither does one whose tries never finished.
 */
export function durationOf(
    attempts: readonly AttemptEvent[],
    outcome: StepOutcome,
    now: number,
): number | null {
    const started = boundOf(
        attempts.map((one) => one.started_at),
        'earliest',
    )
    if (outcome === 'running') {
        const from = started === null ? Number.NaN : Date.parse(started)
        return Number.isNaN(from) ? null : Math.max(0, now - from)
    }
    return elapsedBetween(
        started,
        boundOf(
            attempts.map((one) => one.finished_at),
            'latest',
        ),
    )
}

/**
 * How long the step waited for a worker: claimable until each try was taken up.
 *
 * `available_at` IS WHEN AN ATTEMPT BECAME CLAIMABLE, so queued time is workers being busy and
 * nothing else -- a retry's backoff sits before that moment and is waiting, not queueing.
 * Nothing is said about a step whose tries never started: what it sat through is the time of
 * the steps above it.
 */
export function queuedOf(attempts: readonly AttemptEvent[]): number | null {
    return foldedOf(attempts, (attempt) =>
        attempt.started_at === null
            ? null
            : elapsedBetween(attempt.available_at ?? attempt.created_at, attempt.started_at),
    )
}

/**
 * How long the step was parked on purpose: a retry's backoff, and the gaps between probes.
 *
 * THE LAST PROBE IS WHERE WAITING ENDS: an attempt keeps the moment it first started across
 * every probe, and `heartbeat_at` is when the last one took it up, so everything between the
 * two is parked time plus the probes before that one. An attempt still parked is measured
 * against the clock the screen already ticks.
 */
export function waitingOf(attempts: readonly AttemptEvent[], now: number): number | null {
    return foldedOf(attempts, (attempt) => {
        // Only a retry is written down and then held back; a first attempt becomes claimable
        // when the steps above it finish, and that span is their time rather than its own.
        const backoff =
            (attempt.attempt > 1 ? elapsedBetween(attempt.created_at, attempt.available_at) : 0) ?? 0
        const parked = parkedOf(attempt, now)
        return backoff === 0 && parked === null ? null : backoff + (parked ?? 0)
    })
}

/**
 * Whether two spans of a step read as the same duration.
 *
 * A step that only waited waited for the whole of itself, and a step nothing was free to pick up
 * spent all of itself queued: drawing that span beside the step's own is one fact said twice, so
 * the screen draws only the one. The record still carries all three.
 */
export function readsAsTheWholeStep(span: number | null, whole: number | null): boolean {
    if (span === null || whole === null) return false
    return formatDuration(span) === formatDuration(whole)
}

/**
 * Fold a span measured per try into one number for the step.
 *
 * A RETRY RUNS AFTER THE TRY IT RETRIES AND A FAN-OUT'S ELEMENTS RUN BESIDE EACH OTHER, so one
 * element's tries add up and the elements themselves do not: the longest element speaks for the
 * step. Nothing is said when no try has a span to measure.
 */
function foldedOf(
    attempts: readonly AttemptEvent[],
    spanOf: (attempt: AttemptEvent) => number | null,
): number | null {
    const perElement = new Map<string, number>()
    let measured = false
    for (const attempt of attempts) {
        const span = spanOf(attempt)
        if (span === null) continue
        measured = true
        perElement.set(attempt.run_item_id ?? '', (perElement.get(attempt.run_item_id ?? '') ?? 0) + span)
    }
    return measured ? Math.max(...perElement.values()) : null
}

/**
 * How long one try sat between its probes, or nothing when it never parked.
 *
 * A deadline or a cancel reaches a try where it lies, so nothing was probing when a skipped or
 * cancelled one settled and the whole span from its first probe on was a wait.
 */
function parkedOf(attempt: AttemptEvent, now: number): number | null {
    if (attempt.poke_count === 0 || attempt.started_at === null) return null
    const ended = attempt.status === 'skipped' || attempt.status === 'cancelled'
    const last = ended ? attempt.finished_at : (attempt.heartbeat_at ?? attempt.started_at)
    const until = attempt.finished_at === null ? now : Date.parse(last ?? attempt.started_at)
    const from = Date.parse(attempt.started_at)
    if (Number.isNaN(until) || Number.isNaN(from)) return null
    return Math.max(0, until - from)
}

/** The earliest or the latest of some instants, ignoring the ones that are not there. */
function boundOf(instants: readonly (string | null)[], want: 'earliest' | 'latest'): string | null {
    let best: string | null = null
    let bestAt = 0
    for (const one of instants) {
        if (one === null || one === '') continue
        const at = Date.parse(one)
        if (Number.isNaN(at)) continue
        if (best === null || (want === 'earliest' ? at < bestAt : at > bestAt)) {
            best = one
            bestAt = at
        }
    }
    return best
}

/**
 * Whether `items: continue` absorbed this step's failed elements.
 *
 * THE PINNED NODE'S OUTCOME IS THE ONE ITS DEPENDENTS SAW, and it is the only thing on the wire
 * that tells the two item policies apart: a fan-out under `fail_fast` with a failed element is
 * failed, and one under `continue` with an element left to succeed is succeeded while still
 * counting the failures. So a node that succeeded with failures behind it is a tolerated one,
 * and a fan-out every element failed is not -- that one stays failed, exactly as the engine has
 * it.
 */
export function toleratedFanOut(view: StepView): boolean {
    return view.node.fan_out && view.node.items_failed > 0 && view.node.outcome === 'succeeded'
}

/**
 * What state a node is drawn in, which is its outcome except where a failure was tolerated.
 *
 * FOLDING THE ATTEMPTS CANNOT SEE THE ITEM POLICY. `outcomeOf` reads the element states and a
 * failed element makes the step failed, which is right under `fail_fast` and wrong under
 * `continue`: there the run carried on and settled as completed with errors, so the box that
 * paints itself failed disagrees with the chip in the topbar about the same step. A tolerated
 * fan-out takes the run's own word for it and is drawn in the completed-with-errors hue.
 */
export function nodeTone(view: StepView): AnyStatus {
    if (!toleratedFanOut(view)) return view.outcome
    return view.outcome === 'failed' || view.outcome === 'succeeded' ? 'completed_with_errors' : view.outcome
}

/** The words a counts strip says: how many elements are in each state. */
function countsLabel(counts: readonly ItemCount[]): string {
    return counts.map((count) => LABELS.runs.node_item_count(String(count.count), count.status)).join(' · ')
}

/**
 * One step as the run's graph draws it.
 *
 * THE BOX SAYS WHAT THE EDITOR SAYS OF THE SAME STEP: the title is the name the document gave it
 * and its key otherwise, and the second line is the block, with the key in front where the title
 * is a name. A reply says whether it was sent in place of its duration, and keeps the room of the
 * longer word so the box does not widen when it settles.
 *
 * WHAT IT IS DRAWN IN IS `nodeTone`, so a fan-out whose failures the run tolerated is amber.
 *
 * A FAN-OUT IS THIS ONE BOX: its elements are chips inside it while there are few enough to name,
 * a counts line once there are not, and what it waits for before it has any. A retrying element's
 * chip keeps the room of its countdown's widest, so the box does not move every second.
 *
 * WHAT THE STEP IS DOING IS THE HINT, the box's tooltip, with the percentage a live wait reports.
 * A source's second line says, pointed at, what it listens to.
 */
export function runStepOf(view: StepView, needs: string[]): RunStep {
    const heading = headingOf(view.node)
    const source = view.node.kind === 'source'
    const sent = view.node.kind === 'reply' ? replySent(view.latest) : null
    const kind =
        sent === null
            ? view.node.block
            : `${view.node.block} · ${sent ? LABELS.runs.reply.sent : LABELS.runs.reply.not_sent}`
    const lineOf = (what: string) => (heading.code === null ? what : `${heading.code} · ${what}`)
    const hint =
        view.detail !== null && view.progress !== null
            ? LABELS.runs.node_hint(view.detail, String(Math.round(view.progress * 100)))
            : view.detail
    const reserve: string[] = []
    if (view.node.kind === 'reply') reserve.push(lineOf(`${view.node.block} · ${LABELS.runs.reply.not_sent}`))
    const step: RunStep = {
        code: view.node.code,
        kind,
        needs,
        status: nodeTone(view),
        ...(heading.named ? { name: heading.title } : {}),
        ...(view.duration_ms === null || sent !== null ? {} : { duration_ms: view.duration_ms }),
        ...(view.progress === null ? {} : { progress: view.progress }),
        ...(hint === null ? {} : { hint }),
        ...(source
            ? { source: true, icon: ICONS.source, lineHint: LABELS.editor.canvas.listens_to(lineOf(kind)) }
            : {}),
    }
    if (!view.node.fan_out) return reserve.length === 0 ? step : { ...step, reserve }
    if (view.items > 0) step.count = counted(view.items, LABELS.runs.node_items)(String(view.items))
    const strip = view.strip
    if (strip.kind === 'empty') step.itemsSummary = emptyStripLabel(view)
    else if (strip.kind === 'counts') step.itemsSummary = countsLabel(strip.counts)
    else {
        const widest = LABELS.runs.retry_try_in('99', '999')
        step.items = strip.items.map((item) =>
            item.retry === null
                ? { id: item.id, label: item.key, status: item.status }
                : { id: item.id, label: item.key, status: item.status, note: item.retry, reserve: widest },
        )
    }
    return reserve.length === 0 ? step : { ...step, reserve }
}

/** Every step of the run as its graph draws it, each needing the steps its edges come from. */
export function runSteps(dag: DagView, views: readonly StepView[]): RunStep[] {
    const needs = new Map<string, string[]>()
    for (const [from, to] of dag.edges) needs.set(to, [...(needs.get(to) ?? []), from])
    return views.map((view) => runStepOf(view, needs.get(view.node.code) ?? []))
}

/** Every node of the graph as the screen draws it, in the order the API laid them out. */
export function stepViews(state: RunDetailState, now: number): StepView[] {
    return state.dag.nodes.map((node) => {
        const attempts = stepAttempts(node, attemptsForStep(state, node.code))
        const outcome = outcomeOf(attempts, node.outcome)
        return {
            node,
            outcome,
            attempts,
            items: node.fan_out ? itemsTotal(node, attempts) : 0,
            latest: latestOf(attempts),
            detail: detailOf(latestOf(attempts), node),
            duration_ms: durationOf(attempts, outcome, now),
            queued_ms: queuedOf(attempts),
            waiting_ms: waitingOf(attempts, now),
            progress: progressOf(latestOf(attempts)),
            strip: node.fan_out ? itemStrip(elementsOf(attempts), now) : { kind: 'empty' },
        }
    })
}
