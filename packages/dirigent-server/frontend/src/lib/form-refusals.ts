/**
 * What a form's schema check refuses, as one sentence per field.
 *
 * ONE JUDGE PER FIELD. sokkel-ui's `SchemaForm` refuses a value at its control by checking the
 * value against the form's schema. A list of refusals drawn beside the form reads the same check
 * of the same schema, so a field is never refused at its control and passed in the list, or the
 * other way round.
 *
 * A VALUE WRITTEN AS A REFERENCE IS NOT CHECKED under `deferred`, exactly as the form leaves it
 * alone: `${...}` stands wherever a value goes in a document, and the run resolves it.
 *
 * Only what stops a submit is listed; a warning, such as a deprecated field, is the control's.
 */

import type { Path, SchemaIssue } from '@winterop-com/sokkel-ui/schema/issues'
import { withoutDeferred } from '@winterop-com/sokkel-ui/schema/issues'
import type { JsonSchema } from '@winterop-com/sokkel-ui/schema/read'

import type { JsonMap } from '@/lib/api'
import { deferReference } from '@/lib/form-schema'
import { counted, LABELS } from '@/lib/labels'
import { optionLabel } from '@/lib/schema-form'

/** The schema check: every issue a schema finds with a value, each at its path. */
export type SchemaCheck = (schema: JsonSchema, value: unknown) => SchemaIssue[]

/**
 * Every field the check refuses, by its key, with the first thing wrong with it.
 *
 * `whole` names the form itself, for an issue about the value as a whole rather than one field.
 */
export function refusalsOf(
    check: SchemaCheck,
    schema: JsonSchema,
    value: JsonMap,
    { deferred = false, whole }: { deferred?: boolean; whole: string },
): Record<string, string> {
    const issues = withoutDeferred(check(schema, value), value, deferred ? deferReference : undefined)
    const refusals: Record<string, string> = {}
    for (const issue of issues) {
        if (issue.tone !== 'critical') continue
        const path: Path = issue.kind === 'additional' ? [...issue.path, issue.property] : issue.path
        const key = path.length === 0 ? whole : String(path[0])
        if (key in refusals) continue
        refusals[key] = sentence(issue, path.length === 0 ? whole : path.join('.'))
    }
    return refusals
}

/** What one issue says about the field at `label`. */
function sentence(issue: SchemaIssue, label: string): string {
    const refusal = LABELS.form.refusal
    switch (issue.kind) {
        case 'required':
            return refusal.required(label)
        case 'type':
            return typeSentence(issue.expected, label)
        case 'enum':
            return refusal.one_of(label, issue.values.map((one) => optionLabel(one)).join(', '))
        case 'const':
            return refusal.one_of(label, optionLabel(issue.value))
        case 'minimum':
            return issue.exclusive
                ? refusal.greater_than(label, String(issue.limit))
                : refusal.minimum(label, String(issue.limit))
        case 'maximum':
            return issue.exclusive
                ? refusal.less_than(label, String(issue.limit))
                : refusal.maximum(label, String(issue.limit))
        case 'minLength':
            return counted(issue.limit, refusal.min_length)(label, String(issue.limit))
        case 'maxLength':
            return counted(issue.limit, refusal.max_length)(label, String(issue.limit))
        case 'pattern':
            return refusal.pattern(label, issue.pattern)
        case 'format':
            return refusal.format(label, formatWords(issue.format))
        case 'minItems':
            return counted(issue.limit, refusal.min_items)(label, String(issue.limit))
        case 'maxItems':
            return counted(issue.limit, refusal.max_items)(label, String(issue.limit))
        case 'uniqueItems':
            return refusal.unique_items(label)
        case 'additional':
            return refusal.additional(label)
        case 'deprecated':
        case 'other':
            return refusal.other(label, issue.kind === 'other' ? issue.message : issue.kind)
        case 'unchecked':
            return refusal.unchecked(issue.reason)
    }
}

/** What a value of the wrong JSON type is told it must be. */
function typeSentence(expected: string, label: string): string {
    const refusal = LABELS.form.refusal
    switch (expected) {
        case 'string':
            return refusal.text(label)
        case 'integer':
            return refusal.whole_number(label)
        case 'number':
            return refusal.number(label)
        case 'boolean':
            return refusal.boolean(label)
        case 'object':
            return refusal.map(label)
        case 'array':
            return refusal.list(label)
        default:
            return refusal.shapes(label, expected)
    }
}

/** A format in the reader's words, or as the schema spelled it where there are none. */
function formatWords(format: string): string {
    const words: Readonly<Record<string, string>> = LABELS.form.format
    return words[format.replaceAll('-', '_')] ?? format
}
