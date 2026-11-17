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
import { LABELS } from '@/lib/labels'
import { stepsIn } from '@/lib/pipeline-document'
import stepShapes from '@/lib/step-schema.json'
import { fieldsOf, sameJson, type FieldDescriptor } from '@/lib/schema-form'

/** The step members this form edits, in the order `StepDefinition` declares them. */
export const STEP_KEYS = [
    'rule',
    'for_each',
    'items',
    'timeout',
    'poll',
    'deadline',
    'on_timeout',
    'continue_on_failure',
] as const

/** Each member's shape as `StepDefinition` and `RetryPolicy` declare it, defaults and bounds alike. */
const SHAPES = stepShapes as { step: Record<string, JsonMap>; retry: Record<string, JsonMap> }

/** What each step member's control says about it. */
const STEP_WORDS: Record<(typeof STEP_KEYS)[number], string> = {
    rule: LABELS.editor.step_keys.rule,
    for_each: LABELS.editor.step_keys.for_each,
    items: LABELS.editor.step_keys.items,
    timeout: LABELS.editor.step_keys.timeout,
    poll: LABELS.editor.step_keys.poll,
    deadline: LABELS.editor.step_keys.deadline,
    on_timeout: LABELS.editor.step_keys.on_timeout,
    continue_on_failure: LABELS.editor.step_keys.continue_on_failure,
}

/** What each retry member's control says about it. */
const RETRY_WORDS: Record<string, string> = {
    max_attempts: LABELS.editor.step_keys.max_attempts,
    backoff: LABELS.editor.step_keys.backoff,
    max_backoff: LABELS.editor.step_keys.max_backoff,
    multiplier: LABELS.editor.step_keys.multiplier,
    jitter: LABELS.editor.step_keys.jitter,
}

/** An object schema over these member shapes, each carrying its description. */
function described(shapes: Record<string, JsonMap>, words: Record<string, string>): JsonMap {
    return {
        type: 'object',
        properties: Object.fromEntries(
            Object.entries(shapes).map(([name, shape]) => [name, { ...shape, description: words[name] }]),
        ),
    }
}

/**
 * The step members, as the schema `lib/schema-form` reads.
 *
 * The shapes are `StepDefinition`'s own: the same defaults, the same bounds, and the same words,
 * so a control refuses here what an apply would refuse there. A server test reads the same file
 * against the definition and fails when the two part.
 */
export const STEP_SCHEMA: JsonMap = described(
    {
        ...SHAPES.step,
        for_each: { ...SHAPES.step.for_each, examples: ['${params.regions}', '${steps.spread.items}'] },
    },
    STEP_WORDS,
)

/** `RetryPolicy`, which is one map under `retry` rather than eight keys on the step. */
export const RETRY_SCHEMA: JsonMap = described(SHAPES.retry, RETRY_WORDS)

/** The controls the step section draws, in the order the definition declares them. */
export const stepFields: FieldDescriptor[] = fieldsOf(STEP_SCHEMA)

/** The controls the retry sub-form draws. */
export const retryFields: FieldDescriptor[] = fieldsOf(RETRY_SCHEMA)

/** The part of a schema holding only the named properties, in the schema's order. */
export function pickedSchema(schema: JsonMap, names: readonly string[]): JsonMap {
    const properties = (schema.properties ?? {}) as JsonMap
    return {
        ...schema,
        properties: Object.fromEntries(Object.entries(properties).filter(([name]) => names.includes(name))),
    }
}

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
    const spare =
        written === undefined || written === null || written === '' || sameJson(written, field?.fallback)
    return writeMember(document, step, name, spare ? undefined : written)
}

/** One retry member written, with the whole policy removed once nothing in it differs. */
export function withRetryKey(document: JsonMap, step: string, name: string, value: unknown): JsonMap {
    const field = retryFields.find((one) => one.name === name)
    const held = retryValues(document, step)
    const next: JsonMap = { ...held }
    if (value === undefined || value === null || value === '' || sameJson(value, field?.fallback))
        delete next[name]
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
