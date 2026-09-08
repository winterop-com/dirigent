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
 * WHAT IT DOES NOT UNDERSTAND, IT SAYS SO ABOUT. A list, a map, and a schema with no type at all
 * are edited as JSON in a textarea rather than as a wrong control: the shipped catalog has all
 * three, and guessing at a list of integers with a text box is how a document ends up carrying
 * `"[200]"`. Every shape the catalog actually uses is covered by a test.
 *
 * A FIELD THAT CARRIES A PROGRAM SAYS SO, and the schema is where it says it. A string with
 * `contentMediaType` is a `code` field carrying that media type, so a jq program is edited as
 * the several lines it is written on rather than crammed into one box. Every other string stays
 * one line: what earns an editor is the schema saying the value is source, not its length.
 *
 * THE SERVER REMAINS THE AUTHORITY. `validateField` checks the bounds the descriptor carries so
 * a form can refuse before it asks, and an apply is what decides.
 */

import type { JsonMap } from '@/lib/api'

/** Which control a field is edited with. */
export type FieldKind = 'text' | 'code' | 'number' | 'integer' | 'switch' | 'select' | 'json'

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
    return arrayAt(schema, 'enum').map((one) => ({
        value: one,
        label: typeof one === 'string' ? one : (JSON.stringify(one) ?? String(one)),
    }))
}

/** Whether two values are the same JSON, which is how a value is matched against a choice. */
export function sameJson(a: unknown, b: unknown): boolean {
    if (Object.is(a, b)) return true
    if (a === undefined || b === undefined) return false
    return JSON.stringify(a) === JSON.stringify(b)
}

/** The string a select addresses one choice by, which is not what the choice reads as. */
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

/**
 * What an empty control shows.
 *
 * A field with a default shows that default, because leaving the box empty is what submits it.
 * A list or a map without one shows the shape it takes instead: a bare textarea teaches
 * nothing, and `east, west` is what somebody types into one that has not said it wants JSON.
 */
function placeholderOf(schema: JsonMap, kind: FieldKind, fallback: unknown): string {
    if (fallback !== undefined && fallback !== null) {
        return kind === 'json' ? (JSON.stringify(fallback) ?? '') : String(fallback)
    }
    if (kind !== 'json') return ''
    if (schema.type === 'array') return '["one", "two"]'
    if (schema.type === 'object') return '{"key": "value"}'
    return ''
}

function boundsOf(schema: JsonMap): Bounds {
    const bounds: Bounds = {}
    for (const key of ['minLength', 'maxLength', 'minimum', 'maximum', 'exclusiveMinimum', 'exclusiveMaximum'] as const) {
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
        const kind = kindOf(resolved.schema)
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
                hint: hintOf(resolved.schema, resolved.branches),
                placeholder: placeholderOf(resolved.schema, kind, fallback),
                bounds: boundsOf(resolved.schema),
                accepts:
                    resolved.branches.length > 1
                        ? resolved.branches.map((one) => ({ kind: kindOf(one), bounds: boundsOf(one) }))
                        : [],
            },
        ]
    })
}

/**
 * What is wrong with one value, in the words the person editing it is thinking in, or null.
 *
 * This is the client half of a refusal, and it checks only what the descriptor carries. A
 * document that satisfies every field here can still be refused at apply, which is where the
 * whole document -- its graph, its references, its blocks -- is decided.
 */
export function validateField(field: FieldDescriptor, value: unknown): string | null {
    if (value === undefined) return field.required ? `${field.name} is required` : null
    if (value === null) return field.nullable ? null : `${field.name} may not be null`

    if (field.accepts.length === 0) {
        return shapeProblem(field, { kind: field.kind, bounds: field.bounds }, value)
    }
    // A union: the value is fine under any branch. When none takes it, the branch whose
    // type the value already is says what is wrong with it, because "min_size is text"
    // about a badly written size sends somebody looking at the wrong thing.
    const problems = field.accepts.map((branch) => shapeProblem(field, branch, value))
    if (problems.includes(null)) return null
    const typed = field.accepts.findIndex((branch) => typeMatches(branch.kind, value))
    if (typed !== -1) return problems[typed] ?? null
    return `${field.name} is ${field.accepts.map((branch) => wordFor(branch.kind)).join(' or ')}`
}

/** What is wrong with a value under one shape, or null. */
function shapeProblem(field: FieldDescriptor, shape: BranchShape, value: unknown): string | null {
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
            return typeof value === 'string' ? textProblem(field, shape.bounds, value) : `${field.name} is text`
        case 'number':
        case 'integer':
            return typeof value === 'number' && Number.isFinite(value)
                ? numberProblem(field, shape, value)
                : `${field.name} is a number`
        case 'json':
            return null
    }
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
export function validateFields(fields: FieldDescriptor[], values: JsonMap): Record<string, string> {
    const problems: Record<string, string> = {}
    for (const field of fields) {
        const problem = validateField(field, values[field.name])
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
 */
export function parseInput(field: FieldDescriptor, text: string): Parsed {
    if (text.trim() === '') return { ok: true, value: undefined }
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

/** The default this field falls back to, as one line, or null when it declares none. */
export function fallbackText(field: FieldDescriptor): string | null {
    if (field.fallback === undefined || field.fallback === null) return null
    if (field.kind === 'json') return JSON.stringify(field.fallback) ?? null
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
