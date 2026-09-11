/**
 * What a new rule needs before it can be declared, decided as pure functions.
 *
 * A DIALOG ASKS ONE QUESTION AND GETS ONE SENTENCE. Each of these answers the reason Create is
 * shut, or nothing at all, so the dialog itself holds no rules about what a rule is -- the same
 * shape `lib/trigger-form` answers for a schedule and a webhook.
 */

import { LOG_NOTIFIER, type AlertEvent, type AlertScope } from '@/lib/alerting'

/** What the code box accepts, which is what the server's own `EntityName` accepts. */
const CODE = /^[a-z0-9]+(?:[-_][a-z0-9]+)*$/u

/** What a duration reads as: a number and a unit, or several of both. */
const DURATION = /^(?:\d+(?:ms|s|m|h|d|w))+$/u

/** What the subject field may read, said once so the hint and the docs cannot disagree. */
export const SUBJECT_REFERENCES = 'pipeline, status, id, error, trigger, duration_ms and url'

/** The hint under the subject box: what a template may reach for, and nothing else. */
export const SUBJECT_HINT = `A Jinja template: {{ run.* }} reads the run's ${SUBJECT_REFERENCES}.`

/** The help under the body's label: the same facts, and the report document beside them. */
export const BODY_HINT =
    "A Jinja template over the run's facts; report is the run's report document when it has one."

/** What a subject and a body are written in. `TEMPLATE_MEDIA_TYPE` in dirigent_common. */
export const TEMPLATE_MEDIA_TYPE = 'text/x-jinja'

/** A box left empty is a field nobody set, which is null on the wire rather than "". */
export function given(typed: string): string | null {
    const trimmed = typed.trim()
    return trimmed === '' ? null : trimmed
}

/** The two scopes, in the order the control offers them. */
export const SCOPES: readonly { value: AlertScope; label: string }[] = [
    { value: 'global', label: 'Every pipeline' },
    { value: 'pipeline', label: 'One pipeline' },
]

/** What each event is called on screen, in plain product English rather than the wire's word. */
export const EVENT_LABELS: Record<AlertEvent, string> = {
    run_failed: 'Failed',
    run_completed_with_errors: 'Completed with errors',
    run_succeeded: 'Succeeded',
    run_stuck: 'Stuck',
}

/** Whether this notifier delivers through a credential at all. Only the log one does not. */
export function needsConnection(notifier: string): boolean {
    return notifier !== '' && notifier !== LOG_NOTIFIER
}

/** What a new rule is declared with, as the dialog holds it before it is a request. */
export interface RuleDraft {
    code: string
    scope: AlertScope
    pipeline: string
    notifier: string
    connection: string
    throttle: string
}

/**
 * Why Create is shut on a new rule, or nothing when it is not.
 *
 * The order is the order somebody fills the form in, so the sentence moves down the dialog
 * rather than naming the last box first.
 */
export function unreadyRule(draft: RuleDraft): string | undefined {
    if (draft.code.trim() === '') return 'A rule is addressed by its code, and this one has none.'
    if (!CODE.test(draft.code.trim())) return 'A code is lowercase words joined by - or _.'
    if (draft.scope === 'pipeline' && draft.pipeline === '')
        return 'A rule watching one pipeline names that pipeline, and this one names none.'
    if (draft.notifier === '') return 'A rule delivers through a channel, and this one names none.'
    if (needsConnection(draft.notifier) && draft.connection === '') {
        return `The ${draft.notifier} channel delivers through a connection, and this one names none.`
    }
    if (!DURATION.test(draft.throttle.trim())) return 'A throttle is a duration, such as 15m.'
    return undefined
}

/** Why Send is shut on a test message, or nothing when it is not. */
export function unreadyTest(notifier: string, connection: string): string | undefined {
    if (notifier === '') return 'A test goes through a channel, and this one names none.'
    if (needsConnection(notifier) && connection === '') {
        return `The ${notifier} channel delivers through a connection, and this one names none.`
    }
    return undefined
}
