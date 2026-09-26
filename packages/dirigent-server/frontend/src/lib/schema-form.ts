/**
 * A JSON Schema, read as the fields of a form.
 *
 * A block publishes its config as a JSON Schema and a pipeline publishes its parameters as one,
 * so the step form and the run dialog are the same problem twice. This module is the whole of
 * the decision -- schema in, field descriptors out -- and the components render descriptors and
 * decide nothing.
 *
 * THE LABEL IS THE KEY, not the schema's `title`. What is being edited is a document, and the
 * word an author writes in that document is `max_input` rather than "Max Input"; a form that
 * renamed it would be teaching the wrong name for the thing it is editing. The `description` is
 * the help under the label, which is what the schema carries prose for.
 *
 * WHAT IT DOES NOT UNDERSTAND, IT SAYS SO ABOUT. A list and a schema with no type at all are
 * edited as JSON in a textarea rather than as a wrong control: the shipped catalog has both, and
 * guessing at a list of integers with a text box is how a document ends up carrying `"[200]"`.
 * Every shape the catalog actually uses is covered by a test.
 *
 * A MAP OF SCALARS IS A TABLE OF PAIRS. An object schema whose `additionalProperties` names one
 * scalar type, or a union of them, is the `pairs` kind -- `headers`, `env`, `query` -- and its
 * table writes the plain object the document carries, in the order its rows are in. A map of
 * anything else stays JSON: `pipeline.run`'s `params` holds any JSON value, and a cell cannot.
 *
 * A FIELD THAT CARRIES A PROGRAM SAYS SO, and the schema is where it says it. A string with
 * `contentMediaType` is a `code` field carrying that media type, so a jq program is edited as
 * the several lines it is written on rather than crammed into one box. Every other string stays
 * one line: what earns an editor is the schema saying the value is source, not its length.
 *
 * A FIELD THAT NAMES A THING SAYS WHICH THING, and the schema is again where it says it. A
 * string with `x-dirigent-ref` holds the code of a connection or of a schema rather than a value
 * of its own, and a form that knows which can draw the thing under the box. Any other word there
 * is a kind this bundle has nothing to draw for, and reads as no reference at all.
 *
 * WHAT A STEP NEEDS IS WHAT IT OPENS WITH. `partition` splits a field list into what the schema
 * requires plus what the document already sets, and the optional keys it does not -- so a block
 * with twenty fields and two answers reads as two.
 *
 * A VALUE WRITTEN AS A REFERENCE IS NOT CHECKED AGAINST THE FIELD IT STANDS IN. `${...}` stands
 * wherever a value goes in a document, and what it stands for has no text, no bounds and no type
 * until the run resolves it, so a field carrying one is checked for nothing else. That holds only
 * where a document is being edited: a run's parameters and a connection's config are values, and
 * the server checks those literally, so `deferred` is what a caller says it is editing.
 *
 * THE SERVER REMAINS THE AUTHORITY. `validateField` checks the bounds the descriptor carries so
 * a form can refuse before it asks, and an apply is what decides.
 */

import type { JsonMap } from '@/lib/api'
import { hasReference } from '@/lib/references'

/** Which control a field is edited with. */
export type FieldKind = 'text' | 'code' | 'number' | 'integer' | 'switch' | 'select' | 'json' | 'pairs'

/** What a field's code addresses, for the two kinds of thing a screen can draw. */
export type ReferenceKind = 'connection' | 'schema'

/** The keyword a block's schema names a reference field with. `Reference` in dirigent_plugin. */
export const REFERENCE_KEYWORD = 'x-dirigent-ref'

const REFERENCE_KINDS: ReadonlySet<string> = new Set<ReferenceKind>(['connection', 'schema'])

/** What `validateField` checks, gathered from the schema the descriptor came from. */
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
    /** What a value of this field addresses, from `x-dirigent-ref`, or null for a plain value. */
    refers: ReferenceKind | null
    /** One line beside the label: the format, an example, or the shapes a union accepts. */
    hint: string | null
    /** What an empty control shows: the default it would submit, else the shape it takes. */
    placeholder: string
    bounds: Bounds
    /**
     * Every shape a several-branch union takes, in the schema's order; empty otherwise.
     *
     * A union is edited as its first branch, but a document may carry any of them -- a
     * `Size` is written `"512kb"` or `4096` -- so what the control validates is the union,
     * not the branch it happens to draw.
     */
    accepts: BranchShape[]
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

/** One branch of a union, reduced to what `validateField` checks. */
export interface BranchShape {
    kind: FieldKind
    bounds: Bounds
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

/**
 * The string a select addresses one choice by, which is not what the choice reads as.
 *
 * It is JSON for every value, strings included, because an enum holding `2` and `"2"` needs two
 * tokens and `optionLabel` is what a reader is shown instead.
 */
export function optionToken(value: unknown): string {
    return JSON.stringify(value) ?? String(value)
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

/** Whether a `pairs` field's cells are switches, which is a map of booleans and nothing else. */
export function switchCell(field: FieldDescriptor): boolean {
    return field.holds.length === 1 && field.holds[0] === 'switch'
}

/**
 * The reader's words for the formats the shipped schemas publish.
 *
 * A hint is copy, not a schema dump: `size` reads as what somebody types into the box, and a
 * format this app has no words for is shown as the schema spelled it, which at least says
 * something rather than nothing.
 */
const FORMAT_WORDS: Readonly<Record<string, string>> = {
    size: 'bytes, or a size such as 1mb',
    duration: 'a duration such as 30s',
    'storage-uri': 'a storage URI such as s3://bucket/key',
    'date-time': 'a date and time such as 2026-03-01T12:00:00Z',
    time: 'a time of day such as 06:30',
    password: 'a secret',
}

/** The one line beside the label: the format, an example, and what a union also accepts. */
function hintOf(schema: JsonMap, branches: JsonMap[]): string | null {
    const parts: string[] = []
    const format = stringAt(schema, 'format')
    const worded = format !== null ? (FORMAT_WORDS[format] ?? format) : null
    if (worded !== null) parts.push(worded)
    if (branches.length > 1 && (format === null || FORMAT_WORDS[format] === undefined)) {
        // A format with words of its own already says what the union takes.
        const shapes = branches.map((one) => wordFor(kindOf(one)))
        parts.push(`${[...new Set(shapes)].join(' or ')}`)
    }
    const examples = arrayAt(schema, 'examples')
    if (examples.length > 0) parts.push(`e.g. ${examples.map((one) => String(one)).join(', ')}`)
    return parts.length === 0 ? null : parts.join(' · ')
}

/** What a `pairs` field says beside its label, when a cell holds anything other than text. */
function pairsHint(holds: FieldKind[]): string | null {
    if (holds.length === 1 && holds[0] === 'text') return null
    return `values are ${wordsOf(holds)}`
}

/** The shapes a cell takes, in reader words, each said once; a number covers the whole ones. */
function wordsOf(kinds: readonly FieldKind[]): string {
    const said = kinds.includes('number') ? kinds.filter((one) => one !== 'integer') : kinds
    return [...new Set(said.map((one) => wordFor(one)))].join(' or ')
}

/**
 * What an empty control shows.
 *
 * A field with a default shows that default, because leaving the box empty is what submits it.
 * A list or a map without one shows the shape it takes instead: a bare textarea teaches
 * nothing, and `east, west` is what somebody types into one that has not said it wants JSON.
 */
function placeholderOf(schema: JsonMap, kind: FieldKind, fallback: unknown): string {
    if (fallback !== undefined && fallback !== null) {
        return jsonWritten(kind) ? (JSON.stringify(fallback) ?? '') : String(fallback)
    }
    if (kind !== 'json') return ''
    if (schema.type === 'array') return '["one", "two"]'
    if (schema.type === 'object') return '{"key": "value"}'
    return ''
}

/** Whether a value of this kind reads as the JSON it is rather than as its own text. */
function jsonWritten(kind: FieldKind): boolean {
    return kind === 'json' || kind === 'pairs'
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

/** What one resolved schema says its value addresses, or null when it says nothing this draws. */
function refersTo(schema: JsonMap): ReferenceKind | null {
    const named = stringAt(schema, REFERENCE_KEYWORD)
    return named !== null && REFERENCE_KINDS.has(named) ? (named as ReferenceKind) : null
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
                refers: refersTo(resolved.schema),
                hint: kind === 'pairs' ? pairsHint(holds) : hintOf(resolved.schema, resolved.branches),
                placeholder: placeholderOf(resolved.schema, kind, fallback),
                bounds: boundsOf(resolved.schema),
                accepts:
                    resolved.branches.length > 1
                        ? resolved.branches.map((one) => ({ kind: kindOf(one), bounds: boundsOf(one) }))
                        : [],
                holds,
            },
        ]
    })
}

/** A field list split into what a form shows and what it folds away. */
export interface Partitioned {
    /** Required fields in schema order, then the optional ones the document already sets. */
    open: FieldDescriptor[]
    /** The optional fields the document does not set, in schema order. */
    folded: FieldDescriptor[]
}

/**
 * Which fields a form opens with and which it folds.
 *
 * A block such as `docker.run` publishes twenty config fields and takes two, so a form that drew
 * all twenty at one weight said nothing about what the step needs. What it needs is what the
 * schema requires plus what the document already carries; the rest is offered behind a link.
 *
 * A field is set when the document carries its key, whatever the value: a switch written `false`
 * is a decision somebody made and stays in front of them.
 */
export function partition(fields: FieldDescriptor[], values: JsonMap): Partitioned {
    const set = (field: FieldDescriptor) => Object.hasOwn(values, field.name)
    return {
        open: [...fields.filter((one) => one.required), ...fields.filter((one) => !one.required && set(one))],
        folded: fields.filter((one) => !one.required && !set(one)),
    }
}

/** What the link over the folded fields reads. */
export function foldLabel(count: number): string {
    return `${String(count)} more field${count === 1 ? '' : 's'}`
}

/**
 * What is wrong with one value, in the words the person editing it is thinking in, or null.
 *
 * This is the client half of a refusal, and it checks only what the descriptor carries. A
 * document that satisfies every field here can still be refused at apply, which is where the
 * whole document -- its graph, its references, its blocks -- is decided.
 *
 * `deferred` says the values are a document's, where `${...}` stands wherever a value goes: a
 * field carrying one is left alone, exactly as `defer_references` leaves it alone on the server.
 * Whether the reference names anything a run will have is the whole document's question, and
 * Validate is what asks it.
 */
export function validateField(field: FieldDescriptor, value: unknown, deferred = false): string | null {
    if (value === undefined) return field.required ? `${field.name} is required` : null
    if (deferred && hasReference(value)) return null
    if (value === null) return field.nullable ? null : `${field.name} may not be null`

    if (field.accepts.length === 0) {
        return shapeProblem(field, { kind: field.kind, bounds: field.bounds }, value, deferred)
    }
    // A union: the value is fine under any branch. When none takes it, the branch whose
    // type the value already is says what is wrong with it, because "min_size is text"
    // about a badly written size sends somebody looking at the wrong thing.
    const problems = field.accepts.map((branch) => shapeProblem(field, branch, value, deferred))
    if (problems.includes(null)) return null
    const typed = field.accepts.findIndex((branch) => typeMatches(branch.kind, value))
    if (typed !== -1) return problems[typed] ?? null
    return `${field.name} is ${field.accepts.map((branch) => wordFor(branch.kind)).join(' or ')}`
}

/** What is wrong with a value under one shape, or null. */
function shapeProblem(
    field: FieldDescriptor,
    shape: BranchShape,
    value: unknown,
    deferred: boolean,
): string | null {
    switch (shape.kind) {
        case 'select':
            if (!field.options.some((option) => sameJson(option.value, value))) {
                return `${field.name} is one of ${field.options.map((option) => option.label).join(', ')}`
            }
            return null
        case 'switch':
            return typeof value === 'boolean' ? null : `${field.name} is true or false`
        case 'text':
        case 'code':
            return typeof value === 'string'
                ? textProblem(field, shape.bounds, value)
                : `${field.name} is text`
        case 'number':
        case 'integer':
            return typeof value === 'number' && Number.isFinite(value)
                ? numberProblem(field, shape, value)
                : `${field.name} is a number`
        case 'pairs':
            return mapProblem(field, value, deferred)
        case 'json':
            return null
    }
}

/**
 * What is wrong with a whole map, or null.
 *
 * Where a document is being edited, a reference standing for the whole field never reaches
 * here: `validateField` has already let it through. One entry of the map may be written as one
 * too, and the same holds for that.
 */
function mapProblem(field: FieldDescriptor, value: unknown, deferred: boolean): string | null {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
        return `${field.name} is a map, or a reference to one`
    }
    for (const [key, held] of Object.entries(value as JsonMap)) {
        if (deferred && hasReference(held)) continue
        if (!fits(field.holds, held)) return `${field.name}.${key} is ${wordsOf(field.holds)}`
    }
    return null
}

/** Whether one entry's value is a shape the map holds. */
function fits(holds: readonly FieldKind[], value: unknown): boolean {
    return holds.some((kind) => typeMatches(kind, value) && (kind !== 'integer' || Number.isInteger(value)))
}

/** Whether a value already has the type a shape edits, whatever its bounds say. */
function typeMatches(kind: FieldKind, value: unknown): boolean {
    switch (kind) {
        case 'text':
        case 'code':
        case 'select':
            return typeof value === 'string'
        case 'number':
        case 'integer':
            return typeof value === 'number'
        case 'switch':
            return typeof value === 'boolean'
        case 'pairs':
            return value !== null && typeof value === 'object' && !Array.isArray(value)
        case 'json':
            return true
    }
}

/** The word a union's refusal names a shape by. */
function wordFor(kind: FieldKind): string {
    switch (kind) {
        case 'text':
        case 'code':
            return 'text'
        case 'integer':
            return 'a whole number'
        case 'number':
            return 'a number'
        case 'switch':
            return 'true or false'
        case 'select':
            return 'one of its options'
        case 'pairs':
            return 'a map'
        case 'json':
            return 'JSON'
    }
}

function textProblem(field: FieldDescriptor, bounds: Bounds, value: string): string | null {
    const { minLength, maxLength, pattern } = bounds
    if (minLength !== undefined && value.length < minLength) {
        return `${field.name} is at least ${String(minLength)} character${minLength === 1 ? '' : 's'}`
    }
    if (maxLength !== undefined && value.length > maxLength) {
        return `${field.name} is at most ${String(maxLength)} characters`
    }
    if (pattern !== undefined && !matches(pattern, value)) return `${field.name} does not match ${pattern}`
    return null
}

/** Whether a value satisfies a schema's pattern. A pattern this engine cannot read refuses nothing. */
function matches(pattern: string, value: string): boolean {
    try {
        return new RegExp(pattern).test(value)
    } catch {
        return true
    }
}

function numberProblem(field: FieldDescriptor, shape: BranchShape, value: number): string | null {
    if (shape.kind === 'integer' && !Number.isInteger(value)) return `${field.name} is a whole number`
    const { minimum, maximum, exclusiveMinimum, exclusiveMaximum } = shape.bounds
    if (minimum !== undefined && value < minimum) return `${field.name} is at least ${String(minimum)}`
    if (maximum !== undefined && value > maximum) return `${field.name} is at most ${String(maximum)}`
    if (exclusiveMinimum !== undefined && value <= exclusiveMinimum) {
        return `${field.name} is greater than ${String(exclusiveMinimum)}`
    }
    if (exclusiveMaximum !== undefined && value >= exclusiveMaximum) {
        return `${field.name} is less than ${String(exclusiveMaximum)}`
    }
    return null
}

/** Every field of a form that has something wrong with it, by name. */
export function validateFields(
    fields: FieldDescriptor[],
    values: JsonMap,
    deferred = false,
): Record<string, string> {
    const problems: Record<string, string> = {}
    for (const field of fields) {
        const problem = validateField(field, values[field.name], deferred)
        if (problem !== null) problems[field.name] = problem
    }
    return problems
}

/** What one control holds, or an error when the text is not the shape the field takes. */
export type Parsed = { ok: true; value: unknown } | { ok: false; message: string }

/**
 * Read what somebody typed as the value the document will carry.
 *
 * EMPTY IS NOT A VALUE. Clearing a control removes the key, so a field left blank falls back to
 * the schema's own default rather than writing an empty string into the document.
 *
 * A REFERENCE IS THE TEXT IT WAS TYPED AS, so a number field a document writes `${params.rows}`
 * in can be typed as well as read. JSON is the exception, because a reference is written there
 * the way every other string is, in quotes.
 */
export function parseInput(field: FieldDescriptor, text: string, deferred = false): Parsed {
    if (text.trim() === '') return { ok: true, value: undefined }
    if (deferred && field.kind !== 'json' && hasReference(text)) return { ok: true, value: text }
    switch (field.kind) {
        case 'number':
        case 'integer': {
            const value = Number(text)
            if (!Number.isFinite(value)) return { ok: false, message: `${field.name} is a number` }
            return { ok: true, value }
        }
        case 'json':
            try {
                return { ok: true, value: JSON.parse(text) }
            } catch (error) {
                return { ok: false, message: error instanceof Error ? error.message : 'that is not JSON' }
            }
        default:
            return { ok: true, value: text }
    }
}

/** One row of a `pairs` table: the key, and whatever text is in the value cell beside it. */
export interface Pair {
    key: string
    text: string
}

/** What is wrong with one cell of a `pairs` table, so the row it is in can be marked. */
export interface PairProblem {
    /** Which row, counted from the top as the table draws them. */
    row: number
    where: 'key' | 'value'
    message: string
}

/**
 * The rows a map opens as: one per entry in the document's own order, then one blank row.
 *
 * THE TRAILING ROW IS WHERE THE NEXT PAIR IS TYPED, so a table always has one and an empty map
 * is that row alone. A map of booleans starts its blank row at `false`, which is a value, so
 * such a pair is written as soon as it is given a key.
 */
export function pairsOf(field: FieldDescriptor, value: unknown): Pair[] {
    const held: JsonMap =
        value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as JsonMap) : {}
    return pairRows(
        field,
        Object.entries(held).map(([key, one]) => ({ key, text: cellText(one) })),
    )
}

/** The rows a table draws: the ones that were typed, and the blank row at the foot. */
export function pairRows(field: FieldDescriptor, rows: readonly Pair[]): Pair[] {
    const blank: Pair = { key: '', text: switchCell(field) ? 'false' : '' }
    const last = rows.length === 0 ? undefined : rows[rows.length - 1]
    const ends = last !== undefined && last.key === '' && last.text === blank.text
    return ends ? [...rows] : [...rows, blank]
}

/** What a value cell shows for a value the document already carries. */
function cellText(value: unknown): string {
    return typeof value === 'string' ? value : (JSON.stringify(value) ?? '')
}

/** The reference a whole map field was written as, or null when the field holds a map. */
export function pairsReference(value: unknown): string | null {
    return typeof value === 'string' ? value : null
}

/**
 * Whether a field gives way to a box, because what it holds is text its own control cannot.
 *
 * A choice, a switch and a key/value table each draw a value the schema describes, and text is
 * none of those: drawn by its own control it would read as unset, off or empty, and the first
 * touch would write that over the document. So the text is drawn instead, and clearing the box
 * brings the control back. A table gives way to any text, having no cell that could hold it; a
 * choice and a switch only to a reference, because any other text is a value they may refuse.
 */
export function drawnAsText(field: FieldDescriptor, value: unknown): boolean {
    if (field.kind === 'pairs') return pairsReference(value) !== null
    return (field.kind === 'select' || field.kind === 'switch') && hasReference(value)
}

/** What is said beside the label of a field written as a reference, or null when it is not. */
export function referenceNote(field: FieldDescriptor, value: unknown): string | null {
    if (!hasReference(value)) return null
    switch (field.kind) {
        case 'pairs':
            return 'a reference, not a table'
        case 'select':
            return 'a reference, not a choice'
        case 'switch':
            return 'a reference, not a switch'
        default:
            return null
    }
}

/**
 * What a table of rows writes: the plain object, in the order the rows are in.
 *
 * A ROW IS A PAIR ONLY ONCE IT IS ONE. A row with no key, a row whose cell is empty, and a row
 * whose cell is not a shape the map holds are all half-typed, so they contribute nothing rather
 * than writing a key with no value into the document. A key written twice is written once, by
 * the first row that carries it, and `pairProblems` is what marks the other.
 */
export function pairsValue(field: FieldDescriptor, rows: readonly Pair[], deferred = false): JsonMap {
    const written: JsonMap = {}
    const seen = new Set<string>()
    for (const row of rows) {
        const key = row.key.trim()
        if (key === '' || seen.has(key)) continue
        seen.add(key)
        const cell = parseCell(field, row.text, deferred)
        if (!cell.ok || cell.value === undefined) continue
        written[key] = cell.value
    }
    return written
}

/** Every cell of a table that is not a value, in the order a reader meets them. */
export function pairProblems(field: FieldDescriptor, rows: readonly Pair[], deferred = false): PairProblem[] {
    const problems: PairProblem[] = []
    const seen = new Set<string>()
    rows.forEach((row, index) => {
        const key = row.key.trim()
        if (key !== '') {
            if (seen.has(key)) {
                problems.push({ row: index, where: 'key', message: `${field.name} carries ${key} twice` })
            }
            seen.add(key)
        }
        const cell = parseCell(field, row.text, deferred)
        if (!cell.ok) problems.push({ row: index, where: 'value', message: cell.message })
    })
    return problems
}

/**
 * Read one value cell as the value the document will carry.
 *
 * THE NARROWEST SHAPE THE MAP TAKES WINS. `http.request`'s `query` takes a string, an integer, a
 * number or a boolean, and `2` in that box is the number 2 rather than the text "2" -- a query
 * string is the same either way, and a map that also took text would otherwise never carry a
 * number at all. Where the map takes text alone, `2` is the text "2" and nothing else.
 *
 * A cell written as a reference is the text it was typed as, whatever the map holds.
 */
export function parseCell(field: FieldDescriptor, text: string, deferred = false): Parsed {
    if (text.trim() === '') return { ok: true, value: undefined }
    if (deferred && hasReference(text)) return { ok: true, value: text }
    const reading = Number(text)
    if (field.holds.includes('integer') && Number.isInteger(reading)) return { ok: true, value: reading }
    if (field.holds.includes('number') && Number.isFinite(reading)) return { ok: true, value: reading }
    if (field.holds.includes('switch') && (text === 'true' || text === 'false')) {
        return { ok: true, value: text === 'true' }
    }
    if (field.holds.includes('text')) return { ok: true, value: text }
    return { ok: false, message: `${field.name} values are ${wordsOf(field.holds)}` }
}

/** The default this field falls back to, as one line, or null when it declares none. */
export function fallbackText(field: FieldDescriptor): string | null {
    if (field.fallback === undefined || field.fallback === null) return null
    if (jsonWritten(field.kind)) return JSON.stringify(field.fallback) ?? null
    return String(field.fallback)
}

/**
 * Whether what is on a form may be sent.
 *
 * A box holding text that is not a value blocks as hard as a value the schema refuses: the
 * document still carries the last thing that parsed, and submitting that would send something
 * other than what is on screen.
 */
export function maySubmit(problems: Record<string, string>, unreadable: ReadonlySet<string>): boolean {
    return Object.keys(problems).length === 0 && unreadable.size === 0
}

/** The unreadable set with one field's state changed, or the same set when it did not change. */
export function withUnreadable(
    current: ReadonlySet<string>,
    name: string,
    message: string | null,
): ReadonlySet<string> {
    const held = current.has(name)
    if (message === null ? !held : held) return current
    const next = new Set(current)
    if (message === null) next.delete(name)
    else next.add(name)
    return next
}

/** What a control shows for a field the document does not carry: the schema's own default. */
export function effectiveValue(field: FieldDescriptor, value: unknown): unknown {
    return value === undefined ? field.fallback : value
}

/** What a control shows for a value the document already carries. */
export function inputText(field: FieldDescriptor, value: unknown): string {
    if (value === undefined || value === null) return ''
    if (field.kind === 'json') return JSON.stringify(value, null, 2) ?? ''
    return String(value)
}
