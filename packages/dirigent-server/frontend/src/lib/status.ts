/**
 * The state machines, as the UI reads them.
 *
 * The strings are `RunStatus`, `AttemptStatus`, `RunItemStatus` and the engine's `StepOutcome`
 * off the wire, unchanged. Each indexes a `--status-<name>` token in index.css directly, so
 * there is no translation table between a status and the colour it is drawn in -- a status this
 * bundle has never heard of falls back to the neutral one rather than rendering uncoloured.
 *
 * TERMINAL IS A DECISION, NOT A LOOK. What is terminal decides whether the event stream stays
 * open, whether Cancel is offered, and whether a replayed frame is allowed to move a state
 * backwards. It is stated once here and read everywhere else.
 */

/** Where a run is. `RunStatus` in dirigent_client.enums. */
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'completed_with_errors' | 'failed' | 'cancelled'

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

/** Whether the engine created an attempt or an operator asked for it. `AttemptKind`. */
export type AttemptKind = 'automatic' | 'manual'

/** How severe one product log entry is. `LogLevel` in dirigent_client.enums. */
export type LogLevel = 'debug' | 'info' | 'warning' | 'error'

/** What started a run. `TriggerKind` in dirigent_client.enums. */
export type TriggerKind = 'adhoc' | 'schedule' | 'webhook' | 'api_token' | 'user' | 'pipeline' | 'backfill'

/** Every state a run can be in, in the order a filter offers them. `RunStatus`. */
export const RUN_STATUSES: readonly RunStatus[] = [
    'queued',
    'running',
    'succeeded',
    'completed_with_errors',
    'failed',
    'cancelled',
]

/** Any state string that indexes a status token. */
export type AnyStatus = RunStatus | AttemptStatus | ItemStatus | StepOutcome

/** The run states nothing will move a run out of. `TERMINAL_RUN_STATUSES` in the client. */
const TERMINAL_RUN: ReadonlySet<string> = new Set(['succeeded', 'completed_with_errors', 'failed', 'cancelled'])

/** The outcomes nothing will move a step out of. `StepOutcome`, minus the two live ones. */
const TERMINAL_STEP: ReadonlySet<string> = new Set(['succeeded', 'failed', 'skipped', 'cancelled'])

/** The attempt states nothing will move an attempt out of. */
const TERMINAL_ATTEMPT: ReadonlySet<string> = new Set(['succeeded', 'failed', 'skipped', 'cancelled'])

/** Every status that has a `--status-<name>` token, which is the union of the machines above. */
const TOKENS: ReadonlySet<string> = new Set([
    'pending',
    'queued',
    'running',
    'waiting',
    'succeeded',
    'completed_with_errors',
    'failed',
    'skipped',
    'cancelled',
    'sending',
    'sent',
])

/** Where the neutral pair sits, for a status this bundle was built before. */
const FALLBACK = 'pending'

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
 * The custom properties `.status-chip` and the graph node read: the state's hue and its ink.
 *
 * The wire spells a state with underscores and CSS spells a custom property with hyphens, so
 * `completed_with_errors` indexes `--status-completed-with-errors`. An undefined custom property
 * paints nothing at all, which is why a state this bundle has never heard of takes the neutral
 * pair rather than a name that resolves to no colour.
 */
export function statusTokens(status: string): { '--chip': string; '--chip-ink': string } {
    const name = (TOKENS.has(status) ? status : FALLBACK).replaceAll('_', '-')
    return { '--chip': `var(--status-${name})`, '--chip-ink': `var(--status-${name}-ink)` }
}

/** A status as a person reads it: the wire's underscores are the wire's, not a reader's. */
export function statusLabel(status: string): string {
    return status.replaceAll('_', ' ')
}
