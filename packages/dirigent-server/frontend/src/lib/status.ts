/**
 * The state machines, as the UI reads them.
 *
 * The strings are `RunStatus`, `AttemptStatus`, `RunItemStatus` and the engine's `StepOutcome`
 * off the wire, unchanged. Each is drawn in one color from `LOOKS`, a `--status-<name>` token, and
 * said in one word from the catalogue; `STATUSES` hands both to sokkel-ui's status parts. A status
 * this bundle has never heard of falls back to the neutral pair rather than rendering uncolored.
 *
 * TERMINAL IS A DECISION, NOT A LOOK. What is terminal decides whether the event stream stays
 * open, whether Cancel is offered, and whether a replayed frame is allowed to move a state
 * backwards. It is stated once here and read everywhere else.
 */

import type { StatusColor, StatusMap } from '@winterop-com/sokkel-ui/StatusChip'

import { LABELS } from '@/lib/labels'

/** Where a run is. `RunStatus` in dirigent_client.enums. */
export type RunStatus =
    | 'queued'
    | 'running'
    | 'paused'
    | 'succeeded'
    | 'completed_with_errors'
    | 'failed'
    | 'cancelled'

/** Where one try of one step is. `AttemptStatus` in dirigent_client.enums. */
export type AttemptStatus =
    | 'pending'
    | 'queued'
    | 'running'
    | 'waiting'
    | 'succeeded'
    | 'failed'
    | 'skipped'
    | 'cancelled'

/** Where one element of a fan-out step is. `RunItemStatus` in dirigent_client.enums. */
export type ItemStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped'

/** What a step as a whole amounts to. `StepOutcome` in dirigent_core.engine.state. */
export type StepOutcome = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'cancelled'

/** Whether the engine created an attempt, an operator asked for it, or an input arrived as it. `AttemptKind`. */
export type AttemptKind = 'automatic' | 'manual' | 'received'

/** How the input a source's attempt holds arrived. `EntryVia` in dirigent_client.enums. */
export type EntryVia = 'request' | 'poll' | 'hold' | 'hand' | 'sample'

/** How severe one product log entry is. `LogLevel` in dirigent_client.enums. */
export type LogLevel = 'debug' | 'info' | 'warning' | 'error'

/** What started a run. `TriggerKind` in dirigent_client.enums. */
export type TriggerKind =
    | 'adhoc'
    | 'schedule'
    | 'api_token'
    | 'user'
    | 'pipeline'
    | 'backfill'
    | 'source'
    | 'rerun'

/** Every state a run can be in, in the order a filter offers them. `RunStatus`. */
export const RUN_STATUSES: readonly RunStatus[] = [
    'queued',
    'running',
    'paused',
    'succeeded',
    'completed_with_errors',
    'failed',
    'cancelled',
]

/** Any state string that indexes a status token. */
export type AnyStatus = RunStatus | AttemptStatus | ItemStatus | StepOutcome

/** The run states nothing will move a run out of. `TERMINAL_RUN_STATUSES` in the client. */
const TERMINAL_RUN: ReadonlySet<string> = new Set([
    'succeeded',
    'completed_with_errors',
    'failed',
    'cancelled',
])

/** The outcomes nothing will move a step out of. `StepOutcome`, minus the two live ones. */
const TERMINAL_STEP: ReadonlySet<string> = new Set(['succeeded', 'failed', 'skipped', 'cancelled'])

/** The attempt states nothing will move an attempt out of. */
const TERMINAL_ATTEMPT: ReadonlySet<string> = new Set(['succeeded', 'failed', 'skipped', 'cancelled'])

/**
 * The color each state is drawn in, and whether it is happening now, so its dot pulses. `paused`
 * is held rather than going, so it takes the not-started color; a delivery's `sending` and
 * `sent` are drawn as the run states they mean.
 */
const LOOKS: Readonly<Record<string, { color: StatusColor; live?: boolean }>> = {
    pending: { color: 'pending' },
    queued: { color: 'queued', live: true },
    running: { color: 'running', live: true },
    waiting: { color: 'waiting', live: true },
    paused: { color: 'pending' },
    succeeded: { color: 'succeeded' },
    completed_with_errors: { color: 'completed_with_errors' },
    failed: { color: 'failed' },
    skipped: { color: 'skipped' },
    cancelled: { color: 'cancelled' },
    sending: { color: 'running', live: true },
    sent: { color: 'succeeded' },
}

/** Where the neutral pair sits, for a status this bundle was built before. */
export const FALLBACK: StatusColor = 'pending'

/** Report whether a run has settled, which is what closes the event stream. */
export function runSettled(status: string): boolean {
    return TERMINAL_RUN.has(status)
}

/** Report whether a step has settled, which is what makes its log the whole of what it wrote. */
export function stepSettled(outcome: string): boolean {
    return TERMINAL_STEP.has(outcome)
}

/** Report whether an attempt has settled, which is what a replayed frame may not undo. */
export function attemptSettled(status: string): boolean {
    return TERMINAL_ATTEMPT.has(status)
}

/**
 * The custom properties the graph node, an attempt's rail and a progress line read: the state's
 * hue and its ink.
 *
 * The wire spells a state with underscores and CSS spells a custom property with hyphens, so
 * `completed_with_errors` indexes `--status-completed-with-errors`. An undefined custom property
 * paints nothing at all, which is why a state this bundle has never heard of takes the neutral
 * pair rather than a name that resolves to no colour.
 */
export function statusTokens(status: string): { '--chip': string; '--chip-ink': string } {
    const name = colorOf(status).replaceAll('_', '-')
    return { '--chip': `var(--status-${name})`, '--chip-ink': `var(--status-${name}-ink)` }
}

/** The color a state is drawn in, the neutral pair for one this bundle does not know. */
function colorOf(status: string): StatusColor {
    return Object.hasOwn(LOOKS, status) ? LOOKS[status].color : FALLBACK
}

/** What each state of the two machines is called, keyed by the wire's own value. */
const WORDS: Readonly<Record<string, string>> = {
    ...Object.fromEntries(Object.entries(LABELS.state.run).map(([status, forms]) => [status, forms.chip])),
    ...LABELS.state.attempt,
}

/**
 * A status as a person reads it.
 *
 * A state with no entry is spelled from the wire, underscores and all. That is the one place in
 * the app where a word a person reads was not written in the catalogue, and it cannot be
 * otherwise: a plugin's state, and a notification's `sending` and `sent`, are not this table's.
 */
export function statusLabel(status: string): string {
    return WORDS[status] ?? status.replaceAll('_', ' ')
}

/**
 * Every state this app names, in its words and its color, for the `StatusProvider` around the app:
 * a `StatusChip` or a `Dot` given a status reads it from there.
 */
export const STATUSES: StatusMap = Object.fromEntries(
    Object.entries(LOOKS).map(([status, look]) => [status, { label: statusLabel(status), ...look }]),
)
