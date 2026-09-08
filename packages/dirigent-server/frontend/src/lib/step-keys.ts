/**
 * The engine semantics around a step, read as a form.
 *
 * A STEP IS MORE THAN THE BLOCK IT RUNS. `for_each`, `rule`, `items`, `retry`, the timings and
 * `on_timeout` are what the engine does with that block, and a panel showing only the block's
 * config draws a fan-out as a plain step. The shapes here mirror `StepDefinition`, and
 * `lib/schema-form` turns them into descriptors, so these are the config form's own controls.
 *
 * A DEFAULT IS NOT WRITTEN DOWN. A document carries what differs from the definition's defaults,
 * so choosing `all_success` removes `rule` rather than spelling it out, and an emptied box
 * removes its key. The control still shows the default, which is what would run.
 *
 * `for_each` IS A REFERENCE OR A LIST, and both are typed into one box: text that reads as a
 * JSON list is carried as a list, and anything else is carried as the reference it was written
 * as. A list already in the document is shown as the JSON it is, so what is read back is what
 * was typed.
 */

import type { JsonMap } from '@/lib/api'
import { stepsIn } from '@/lib/pipeline-document'
import { fieldsOf, sameJson, type FieldDescriptor } from '@/lib/schema-form'

/** The step members this form edits, in the order `StepDefinition` declares them. */
export const STEP_KEYS = ['rule', 'for_each', 'items', 'timeout', 'poll', 'deadline', 'on_timeout', 'continue_on_failure'] as const

/** A duration as somebody writes it, which is the shape `Duration` accepts. */
const DURATION: JsonMap = { type: 'string', format: 'duration' }

/**
 * The step members, as the schema `lib/schema-form` reads.
 *
 * This mirrors `StepDefinition` in `dirigent_core.engine.definition`: the same defaults, the
 * same bounds, and the same words, so a control refuses here what an apply would refuse there.
 */
const STEP_SCHEMA: JsonMap = {
    type: 'object',
    properties: {
        rule: {
            type: 'string',
            enum: ['all_success', 'all_done', 'one_failed', 'always'],
            default: 'all_success',
            description: 'When this step becomes ready, over the steps it waits for.',
        },
        for_each: {
            anyOf: [{ type: 'string' }, { type: 'array', items: {} }],
            description: 'A reference to a list, or a literal list: one run item per element.',
            examples: ['${params.regions}'],
        },
        items: {
            type: 'string',
            enum: ['fail_fast', 'continue'],
            default: 'fail_fast',
            description: 'Whether one failed item stops the batch, or the rest carry on.',
        },
        timeout: {
            ...DURATION,
            description: 'How long one attempt may take.',
        },
        poll: { ...DURATION, description: "How often a sensor checks. Defaults to the sensor's own cadence." },
        deadline: {
            ...DURATION,
            description: 'How long the step may wait before the timeout applies.',
        },
        on_timeout: {
            type: 'string',
            enum: ['fail', 'skip'],
            default: 'fail',
            description: 'What an expired deadline does to the step.',
        },
        continue_on_failure: {
            type: 'boolean',
            default: false,
            description: 'Dependents still run when this step fails, and the run completes with errors.',
        },
    },
}

/** `RetryPolicy`, which is one map under `retry` rather than eight keys on the step. */
const RETRY_SCHEMA: JsonMap = {
    type: 'object',
    properties: {
        max_attempts: {
            type: 'integer',
            minimum: 1,
            maximum: 100,
            default: 1,
            description: 'Total attempts, including the first.',
        },
        backoff: { ...DURATION, default: '30s', description: 'The delay after the first failure.' },
        max_backoff: { ...DURATION, default: '1h', description: 'The longest delay between attempts.' },
        multiplier: { type: 'number', minimum: 1, maximum: 10, default: 2, description: 'What each delay is multiplied by.' },
        jitter: {
            type: 'number',
            minimum: 0,
            maximum: 1,
            default: 0.2,
            description: 'How much of the delay is spread randomly.',
        },
    },
}

/** The controls the step section draws, in the order the definition declares them. */
export const stepFields: FieldDescriptor[] = fieldsOf(STEP_SCHEMA)

/** The controls the retry sub-form draws. */
export const retryFields: FieldDescriptor[] = fieldsOf(RETRY_SCHEMA)

/** One step's members, as the controls show them: a list under `for_each` reads as its JSON. */
export function stepKeyValues(document: JsonMap | null, step: string): JsonMap {
    const held = stepsIn(document)[step] ?? {}
    const values: JsonMap = {}
    for (const key of STEP_KEYS) {
        const value = held[key]
        if (value === undefined) continue
        values[key] = key === 'for_each' ? forEachText(value) : value
    }
    return values
}

/** One step's retry policy, or an empty map when it carries none. */
export function retryValues(document: JsonMap | null, step: string): JsonMap {
    const retry = stepsIn(document)[step]?.retry
    if (retry === null || retry === undefined || typeof retry !== 'object' || Array.isArray(retry)) return {}
    return retry as JsonMap
}

/** What a `for_each` box shows: a list as the JSON it is, a reference as itself. */
export function forEachText(value: unknown): string {
    if (typeof value === 'string') return value
    return JSON.stringify(value) ?? ''
}

/** What a `for_each` box writes: text that reads as a JSON list is a list, anything else is text. */
export function forEachValue(value: unknown): unknown {
    if (typeof value !== 'string') return value
    const trimmed = value.trim()
    if (!trimmed.startsWith('[')) return value
    try {
        const parsed: unknown = JSON.parse(trimmed)
        return Array.isArray(parsed) ? parsed : value
    } catch {
        return value
    }
}

/**
 * One step member written, or removed when what was written is what the engine does anyway.
 *
 * A step carrying `rule: all_success` and a step carrying nothing run the same, and the document
 * is what somebody reads, so the one that says nothing is the one that is written.
 */
export function withStepKey(document: JsonMap, step: string, name: string, value: unknown): JsonMap {
    const field = stepFields.find((one) => one.name === name)
    const written = name === 'for_each' ? forEachValue(value) : value
    const spare = written === undefined || written === null || written === '' || sameJson(written, field?.fallback)
    return writeMember(document, step, name, spare ? undefined : written)
}

/** One retry member written, with the whole policy removed once nothing in it differs. */
export function withRetryKey(document: JsonMap, step: string, name: string, value: unknown): JsonMap {
    const field = retryFields.find((one) => one.name === name)
    const held = retryValues(document, step)
    const next: JsonMap = { ...held }
    if (value === undefined || value === null || value === '' || sameJson(value, field?.fallback)) delete next[name]
    else next[name] = value
    return writeMember(document, step, 'retry', Object.keys(next).length === 0 ? undefined : next)
}

/** A document with one member of one step replaced, or dropped when there is no value for it. */
function writeMember(document: JsonMap, step: string, member: string, value: unknown): JsonMap {
    const steps = stepsIn(document)
    const existing = steps[step]
    if (existing === undefined) return document
    const changed: JsonMap = { ...existing }
    if (value === undefined) delete changed[member]
    else changed[member] = value
    return { ...document, steps: { ...steps, [step]: changed } }
}
