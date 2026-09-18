/**
 * The engine's half of a step, gathered into the groups a panel reads it in.
 *
 * A PANEL ASKS ABOUT THE BLOCK FIRST AND THE ENGINE SECOND. What a step does is its config; how
 * the engine runs it -- what it waits for, whether it fans out, how long it may take, what it
 * does with a failure -- is a second half that most steps leave at its defaults. Drawn as one
 * flat list of twelve controls it buried the two keys the step actually answers, so it is read
 * as five groups, each of which says its own state in one line and opens in place.
 *
 * THE KEYS ARE `lib/step-keys`' AND NOTHING HERE REPEATS THEM. `GROUP_OF` names the group each
 * member of `STEP_KEYS` belongs to, so a key added to the definition is a type error here until
 * it is filed, and every control and every default a summary reads comes from the descriptors
 * that module builds from the schema.
 *
 * A SHUT GROUP SAYS WHAT WOULD RUN, NOT WHAT IS WRITTEN DOWN. A document carries only what
 * differs from the definition's defaults, so a summary shows the document's value in body ink
 * and the default it would fall back to in muted ink: either way the line is what the engine
 * would do, and the ink says which of the two somebody chose.
 *
 * `poll` IS A SENSOR'S KEY. An operator never checks anything, so the timing group neither
 * summarises nor draws a poll for one -- unless the document sets it, because a key a step
 * carries is never hidden from the person reading that step.
 */

import type { JsonMap } from '@/lib/api'
import type { FieldDescriptor } from '@/lib/schema-form'
import { forEachText, retryFields, stepFields, STEP_KEYS } from '@/lib/step-keys'

/** Which group of the step panel one part of the engine's half is read in. */
export type StepGroupId = 'depends_on' | 'fan_out' | 'timing' | 'retry' | 'rule'

/** One piece of a shut group's line: the words, and whether the document is what says them. */
export interface SummaryPart {
    text: string
    /** The document carries this value. A part that does not is the default that would run. */
    set: boolean
}

/** One group of the panel: what it is called, what it edits, and what it says while it is shut. */
export interface StepGroup {
    id: StepGroupId
    title: string
    /** The controls the open group draws, in the order the definition declares them. */
    fields: FieldDescriptor[]
    /** The one line the shut row reads, left to right. */
    summary: SummaryPart[]
    /** The summary's parts are step keys, which are drawn as chips rather than as a line. */
    chips: boolean
}

/** The group each step member is edited in. Every key the definition declares is filed here. */
const GROUP_OF: Record<(typeof STEP_KEYS)[number], StepGroupId> = {
    rule: 'rule',
    continue_on_failure: 'rule',
    for_each: 'fan_out',
    items: 'fan_out',
    timeout: 'timing',
    poll: 'timing',
    deadline: 'timing',
    on_timeout: 'timing',
}

/** The step members one group edits, in the order the definition declares them. */
function fieldsIn(group: StepGroupId): FieldDescriptor[] {
    const keys = STEP_KEYS.filter((key) => GROUP_OF[key] === group)
    return stepFields.filter((field) => keys.some((key) => key === field.name))
}

/** What the definition falls back to for one member, as the word a summary reads. */
function fallbackOf(fields: FieldDescriptor[], name: string): string {
    const fallback = fields.find((one) => one.name === name)?.fallback
    return fallback === undefined || fallback === null ? '' : String(fallback)
}

/** Whether the document says anything about one member. An emptied box says nothing. */
function carries(values: JsonMap, name: string): boolean {
    const value = values[name]
    return value !== undefined && value !== null && value !== ''
}

/** What a step waits for: the keys it names, or that it is a root. */
export function dependsOnSummary(prerequisites: readonly string[]): SummaryPart[] {
    if (prerequisites.length === 0) return [{ text: 'nothing; this step is a root', set: false }]
    return prerequisites.map((name) => ({ text: name, set: true }))
}

/** What a step is mapped over, and what one failed element does to the rest. */
export function fanOutSummary(keys: JsonMap): SummaryPart[] {
    if (!carries(keys, 'for_each')) return [{ text: 'off', set: false }]
    const items = carries(keys, 'items')
    return [
        { text: forEachText(keys.for_each), set: true },
        { text: items ? String(keys.items) : fallbackOf(stepFields, 'items'), set: items },
    ]
}

/** How long a step may take, how often a sensor checks, and what an expired deadline does. */
export function timingSummary(keys: JsonMap, sensor: boolean): SummaryPart[] {
    const parts = [duration(keys, 'timeout', 'no timeout')]
    if (sensor || carries(keys, 'poll')) parts.push(duration(keys, 'poll', 'poll its own cadence'))
    parts.push(duration(keys, 'deadline', 'no deadline'))
    const expired = carries(keys, 'on_timeout')
    const chosen = expired ? String(keys.on_timeout) : fallbackOf(stepFields, 'on_timeout')
    parts.push({ text: `on_timeout ${chosen}`, set: expired })
    return parts
}

/** One duration: the key and its value, or what happens without one. */
function duration(keys: JsonMap, name: string, absent: string): SummaryPart {
    if (!carries(keys, name)) return { text: absent, set: false }
    return { text: `${name} ${String(keys[name])}`, set: true }
}

/** How a step is tried again, or that it is not tried again at all. */
export function retrySummary(retry: JsonMap): SummaryPart[] {
    const attempts = retry.max_attempts
    if (attempts === undefined || String(attempts) === fallbackOf(retryFields, 'max_attempts')) {
        return [{ text: 'off', set: false }]
    }
    const backoff = carries(retry, 'backoff')
    const growth = carries(retry, 'multiplier') || carries(retry, 'max_backoff')
    const multiplier = carries(retry, 'multiplier')
        ? String(retry.multiplier)
        : fallbackOf(retryFields, 'multiplier')
    const ceiling = carries(retry, 'max_backoff')
        ? String(retry.max_backoff)
        : fallbackOf(retryFields, 'max_backoff')
    const parts: SummaryPart[] = [
        { text: `${String(attempts)} attempts`, set: true },
        {
            text: `${backoff ? String(retry.backoff) : fallbackOf(retryFields, 'backoff')} backoff`,
            set: backoff,
        },
        { text: `×${multiplier} up to ${ceiling}`, set: growth },
    ]
    // Jitter is a spread nobody asked for until they did, so a policy at the default says nothing
    // about it rather than spending a third of the line on it.
    if (carries(retry, 'jitter')) parts.push({ text: `jitter ${String(retry.jitter)}`, set: true })
    return parts
}

/** When a step becomes ready, and whether its dependents run when it fails. */
export function ruleSummary(keys: JsonMap): SummaryPart[] {
    const chosen = carries(keys, 'rule')
    const parts: SummaryPart[] = [
        { text: chosen ? String(keys.rule) : fallbackOf(stepFields, 'rule'), set: chosen },
    ]
    if (keys.continue_on_failure === true) parts.push({ text: 'continues on failure', set: true })
    return parts
}

/** The panel's groups, in the order they are read, each already summarised. */
export function stepGroups({
    keys,
    retry,
    prerequisites,
    sensor,
}: {
    /** The step members the document carries, from `stepKeyValues`. */
    keys: JsonMap
    /** The step's retry policy, from `retryValues`. */
    retry: JsonMap
    prerequisites: readonly string[]
    /** The block this step runs is a sensor, which is the only kind that polls. */
    sensor: boolean
}): StepGroup[] {
    return [
        {
            id: 'depends_on',
            title: 'Waits for',
            fields: [],
            summary: dependsOnSummary(prerequisites),
            chips: prerequisites.length > 0,
        },
        {
            id: 'fan_out',
            title: 'Fan-out',
            fields: fieldsIn('fan_out'),
            summary: fanOutSummary(keys),
            chips: false,
        },
        {
            id: 'timing',
            title: 'Timing',
            fields: fieldsIn('timing').filter(
                (field) => field.name !== 'poll' || sensor || carries(keys, 'poll'),
            ),
            summary: timingSummary(keys, sensor),
            chips: false,
        },
        { id: 'retry', title: 'Retry', fields: retryFields, summary: retrySummary(retry), chips: false },
        { id: 'rule', title: 'Rule', fields: fieldsIn('rule'), summary: ruleSummary(keys), chips: false },
    ]
}

/** What is wrong with the fields of one group, out of everything wrong with the form. */
export function groupProblems(group: StepGroup, problems: Record<string, string>): Record<string, string> {
    const mine: Record<string, string> = {}
    for (const field of group.fields) {
        const problem = problems[field.name]
        if (problem !== undefined) mine[field.name] = problem
    }
    return mine
}
