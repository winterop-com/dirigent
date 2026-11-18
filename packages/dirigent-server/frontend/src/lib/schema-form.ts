/**
 * A JSON Schema, read as field descriptors: which kind of value each field takes, its bounds,
 * whether it is required, what its enum offers and what it falls back to. The catalog's
 * descriptions, the pipeline pane's parameter list and a step group's summary line read them; the
 * forms themselves, and what they refuse, are sokkel-ui's `SchemaForm`.
 *
 * THE LABEL IS THE KEY, not the schema's `title`. What is being edited is a document, and the
 * word an author writes in that document is `max_input` rather than "Max Input".
 *
 * A MAP OF SCALARS is the `pairs` kind: an object schema whose `additionalProperties` names one
 * scalar type, or a union of them, such as `headers`, `env` and `query`. A map of anything else
 * is `json`, and so are a list and a schema with no type at all.
 *
 * A STRING WITH `contentMediaType` is a `code` field carrying that media type.
 */

import type { JsonMap } from '@/lib/api'
import { LABELS } from '@/lib/labels'

/** Which control a field is edited with. */
export type FieldKind = 'text' | 'code' | 'number' | 'integer' | 'switch' | 'select' | 'json' | 'pairs'

/** What a field's code addresses, for the two kinds of thing a screen can draw. */
export type ReferenceKind = 'connection' | 'schema'

/** The keyword a block's schema names a reference field with. `Reference` in dirigent_plugin. */
export const REFERENCE_KEYWORD = 'x-dirigent-ref'

/** The bounds a schema sets on a value, gathered from the schema the descriptor came from. */
export interface Bounds {
    minLength?: number
    maxLength?: number
    pattern?: string
    minimum?: number
    maximum?: number
    exclusiveMinimum?: number
    exclusiveMaximum?: number
}

/** One field of a generated form. */
export interface FieldDescriptor {
    /** The key in the document, which is also what the label reads. */
    name: string
    kind: FieldKind
    /** The schema's `description`, which is the help text under the label. */
    help: string | null
    /** Whether the schema lists this key as required. */
    required: boolean
    /** The schema also allowed null, so clearing the control is a value rather than nothing. */
    nullable: boolean
    /** What the schema says the value is when the document does not carry the key. */
    fallback: unknown
    /** An enum's choices in the schema's own order; empty for anything but a select. */
    options: FieldOption[]
    /** The `contentMediaType` the schema published, which is the language a `code` field holds. */
    mediaType: string | null
    /** One line beside the label: the format, an example, or the shapes a union accepts. */
    hint: string | null
    bounds: Bounds
    /**
     * Every shape one entry of a `pairs` map takes, in the schema's order; empty otherwise.
     *
     * This is what a value cell is read and refused against: a map of integers refuses `1.5`,
     * a map of booleans alone is a switch, and a map that takes several shapes reads what was
     * typed as the first of them it fits.
     */
    holds: FieldKind[]
}

/** One choice of an enum. */
export interface FieldOption {
    /** The value the document carries, in the JSON type the schema wrote it as. */
    value: unknown
    /** What the choice reads as on screen. */
    label: string
}

/** How far a chain of `$ref`s is followed before it is treated as a shape nothing understands. */
const MAX_DEPTH = 8

/** Read one member of a schema as an object, or nothing. */
function objectAt(schema: JsonMap, key: string): JsonMap | null {
    const value = schema[key]
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
    return value as JsonMap
}

/** Read one member of a schema as an array, or nothing. */
function arrayAt(schema: JsonMap, key: string): unknown[] {
    const value = schema[key]
    return Array.isArray(value) ? value : []
}

function numberAt(schema: JsonMap, key: string): number | undefined {
    const value = schema[key]
    return typeof value === 'number' ? value : undefined
}

function stringAt(schema: JsonMap, key: string): string | null {
    const value = schema[key]
    return typeof value === 'string' ? value : null
}

/**
 * Follow `$ref`s and collapse a nullable union, keeping what the outer schema said.
 *
 * `{"$ref": "#/$defs/Size", "default": "32mb"}` is the definition's shape with the outer
 * default, and `{"anyOf": [X, {"type": "null"}]}` is X that may also be null. Both are how
 * pydantic writes an optional field, and both are one field on a form.
 */
function flatten(
    schema: JsonMap,
    defs: JsonMap,
    depth: number = 0,
): { schema: JsonMap; nullable: boolean; branches: JsonMap[] } {
    if (depth >= MAX_DEPTH) return { schema, nullable: false, branches: [] }

    const reference = stringAt(schema, '$ref')
    if (reference !== null) {
        const target = defs[reference.replace('#/$defs/', '')]
        if (target !== null && typeof target === 'object' && !Array.isArray(target)) {
            const { $ref: _ignored, ...rest } = schema
            const merged = { ...(target as JsonMap), ...rest }
            return flatten(merged, defs, depth + 1)
        }
        return { schema, nullable: false, branches: [] }
    }

    const union = arrayAt(schema, 'anyOf').concat(arrayAt(schema, 'oneOf'))
    if (union.length > 0) {
        const members = union.filter((one): one is JsonMap => one !== null && typeof one === 'object')
        const nulls = members.filter((one) => one.type === 'null')
        const rest = members.filter((one) => one.type !== 'null')
        const { anyOf: _any, oneOf: _one, ...outer } = schema
        if (rest.length === 1) {
            const inner = flatten({ ...rest[0], ...outer }, defs, depth + 1)
            return { ...inner, nullable: inner.nullable || nulls.length > 0 }
        }
        const flattened = rest.map((one) => flatten(one, defs, depth + 1).schema)
        // A union of several shapes is edited as its first one, and says what else it takes.
        const chosen = flattened.length > 0 ? { ...flattened[0], ...outer } : outer
        return { schema: chosen, nullable: nulls.length > 0, branches: flattened }
    }

    return { schema, nullable: false, branches: [] }
}

/**
 * An enum's choices, keeping the value the schema wrote and the words it reads as.
 *
 * A choice submits the JSON the schema listed, so an integer enum sends 1 rather than "1".
 */
function optionsOf(schema: JsonMap): FieldOption[] {
    return arrayAt(schema, 'enum').map((one) => ({ value: one, label: optionLabel(one) }))
}

/**
 * What one choice reads as: a string wears no quotes, and every other value wears its JSON.
 *
 * `GET` and `all_success` are words a document carries, and drawing them `"GET"` would teach a
 * spelling the document does not use. A number, a boolean and null are drawn as the JSON they
 * are, so an enum holding both `2` and `"2"` still reads as two choices.
 */
export function optionLabel(value: unknown): string {
    return typeof value === 'string' ? value : (JSON.stringify(value) ?? String(value))
}

/** Whether two values are the same JSON, which is how a value is matched against a choice. */
export function sameJson(a: unknown, b: unknown): boolean {
    if (Object.is(a, b)) return true
    if (a === undefined || b === undefined) return false
    return JSON.stringify(a) === JSON.stringify(b)
}

/** Which control one resolved schema is edited with. */
function kindOf(schema: JsonMap): FieldKind {
    if (arrayAt(schema, 'enum').length > 0) return 'select'
    switch (schema.type) {
        case 'string':
            return stringAt(schema, 'contentMediaType') === null ? 'text' : 'code'
        case 'integer':
            return 'integer'
        case 'number':
            return 'number'
        case 'boolean':
            return 'switch'
        default:
            return 'json'
    }
}

/** The shapes a value cell is able to hold. A map of anything else is edited as JSON. */
const CELL_KINDS: ReadonlySet<FieldKind> = new Set<FieldKind>(['text', 'integer', 'number', 'switch'])

/**
 * The shapes a map's values take, or empty when this schema is not a map of scalars.
 *
 * A map is an object schema with no `properties` of its own whose `additionalProperties` is a
 * schema rather than a bare `true` or `false`. Its values have to be scalars all the way down:
 * a map of lists, a map of any JSON value, and a map whose values may be null are all shapes a
 * two-column table would have to lie about, so they keep the textarea.
 */
function holdsOf(schema: JsonMap, defs: JsonMap): FieldKind[] {
    if (schema.type !== 'object' || objectAt(schema, 'properties') !== null) return []
    const values = objectAt(schema, 'additionalProperties')
    if (values === null) return []
    const resolved = flatten(values, defs)
    if (resolved.nullable) return []
    const branches = resolved.branches.length > 1 ? resolved.branches : [resolved.schema]
    const kinds = branches.map((one) => kindOf(one))
    return kinds.every((one) => CELL_KINDS.has(one)) ? kinds : []
}

/**
 * The reader's words for the formats the shipped schemas publish.
 *
 * A hint is copy, not a schema dump: `size` reads as what somebody types into the box, and a
 * format this app has no words for is shown as the schema spelled it, which at least says
 * something rather than nothing.
 */
const FORMAT_WORDS: Readonly<Record<string, string>> = LABELS.form.format

/** A schema's `format` as the catalogue keys it: `date-time` is minted as `date_time`. */
const formatWords = (format: string) => FORMAT_WORDS[format.replaceAll('-', '_')]

/** The one line beside the label: the format, an example, and what a union also accepts. */
function hintOf(schema: JsonMap, branches: JsonMap[]): string | null {
    const parts: string[] = []
    const format = stringAt(schema, 'format')
    const worded = format !== null ? (formatWords(format) ?? format) : null
    if (worded !== null) parts.push(worded)
    if (branches.length > 1 && (format === null || formatWords(format) === undefined)) {
        // A format with words of its own already says what the union takes.
        const shapes = branches.map((one) => wordFor(kindOf(one)))
        parts.push(`${[...new Set(shapes)].join(LABELS.form.or)}`)
    }
    const examples = arrayAt(schema, 'examples')
    if (examples.length > 0)
        parts.push(LABELS.form.hint.examples(examples.map((one) => String(one)).join(', ')))
    return parts.length === 0 ? null : parts.join(' · ')
}

/** What a `pairs` field says beside its label, when a cell holds anything other than text. */
function pairsHint(holds: FieldKind[]): string | null {
    if (holds.length === 1 && holds[0] === 'text') return null
    return LABELS.form.hint.pairs(wordsOf(holds))
}

/** The shapes a cell takes, in reader words, each said once; a number covers the whole ones. */
function wordsOf(kinds: readonly FieldKind[]): string {
    const said = kinds.includes('number') ? kinds.filter((one) => one !== 'integer') : kinds
    return [...new Set(said.map((one) => wordFor(one)))].join(LABELS.form.or)
}

function boundsOf(schema: JsonMap): Bounds {
    const bounds: Bounds = {}
    for (const key of [
        'minLength',
        'maxLength',
        'minimum',
        'maximum',
        'exclusiveMinimum',
        'exclusiveMaximum',
    ] as const) {
        const value = numberAt(schema, key)
        if (value !== undefined) bounds[key] = value
    }
    const pattern = stringAt(schema, 'pattern')
    if (pattern !== null) bounds.pattern = pattern
    return bounds
}

/**
 * The fields one schema describes, in the order the schema lists them.
 *
 * A schema that is not an object schema, or that declares no properties, has no fields: a form
 * with nothing on it is what a block taking no config should draw.
 */
export function fieldsOf(schema: JsonMap | null | undefined): FieldDescriptor[] {
    if (schema === null || schema === undefined) return []
    const properties = objectAt(schema, 'properties')
    if (properties === null) return []
    const defs = objectAt(schema, '$defs') ?? {}
    const required = new Set(arrayAt(schema, 'required').map((one) => String(one)))

    return Object.entries(properties).flatMap(([name, raw]) => {
        if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return []
        const resolved = flatten(raw as JsonMap, defs)
        const holds = holdsOf(resolved.schema, defs)
        const kind = holds.length > 0 ? 'pairs' : kindOf(resolved.schema)
        const fallback = resolved.schema.default
        return [
            {
                name,
                kind,
                help: stringAt(resolved.schema, 'description'),
                required: required.has(name),
                nullable: resolved.nullable,
                fallback,
                options: kind === 'select' ? optionsOf(resolved.schema) : [],
                mediaType: stringAt(resolved.schema, 'contentMediaType'),
                hint: kind === 'pairs' ? pairsHint(holds) : hintOf(resolved.schema, resolved.branches),
                bounds: boundsOf(resolved.schema),
                holds,
            },
        ]
    })
}

/** The word a hint names a shape by. */
function wordFor(kind: FieldKind): string {
    switch (kind) {
        case 'text':
        case 'code':
            return LABELS.form.shape.text
        case 'integer':
            return LABELS.form.shape.integer
        case 'number':
            return LABELS.form.shape.number
        case 'switch':
            return LABELS.form.shape.switch
        case 'select':
            return LABELS.form.shape.select
        case 'pairs':
            return LABELS.form.shape.pairs
        case 'json':
            return LABELS.form.shape.json
    }
}
