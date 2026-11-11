/**
 * A JSON Schema as sokkel-ui's `SchemaForm` is handed it.
 *
 * The form labels a field by its schema `title` and falls back to the key in mono. A document's
 * fields are labeled by their key, so every `title` the schema carries is taken out, `$defs`
 * included. A field a connection kind declares secret is marked `writeOnly`, which the form draws
 * as a secret field.
 */

import { fieldSchema, scalarUnion, types, type DeferredValue } from '@winterop-com/sokkel-ui/schema/issues'
import type { JsonSchema } from '@winterop-com/sokkel-ui/schema/read'

import type { JsonMap } from '@/lib/api'
import { hasReference } from '@/lib/references'
import { REFERENCE_KEYWORD, sameJson, type ReferenceKind } from '@/lib/schema-form'

/** The schema keywords whose value is one schema. */
const ONE = ['items', 'additionalProperties', 'not', 'if', 'then', 'else'] as const

/** The schema keywords whose value is a list of schemas. */
const MANY = ['anyOf', 'oneOf', 'allOf', 'prefixItems'] as const

/** The schema keywords whose value is a map of schemas by name. */
const NAMED = ['properties', '$defs', 'definitions', 'patternProperties'] as const

function isMap(value: unknown): value is JsonMap {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** The schema with every `title` keyword taken out, at every depth. */
export function untitled(schema: JsonMap): JsonMap {
    const out: JsonMap = { ...schema }
    if (typeof out.title === 'string') delete out.title
    for (const key of ONE) {
        const held = out[key]
        if (isMap(held)) out[key] = untitled(held)
    }
    for (const key of MANY) {
        const held = out[key]
        if (Array.isArray(held)) out[key] = held.map((one) => (isMap(one) ? untitled(one) : one))
    }
    for (const key of NAMED) {
        const held = out[key]
        if (isMap(held))
            out[key] = Object.fromEntries(
                Object.entries(held).map(([name, one]) => [name, isMap(one) ? untitled(one) : one]),
            )
    }
    return out
}

/** The schema with each named property marked `writeOnly`. */
function sealedFields(schema: JsonMap, secrets: readonly string[]): JsonMap {
    const properties = schema.properties
    if (secrets.length === 0 || !isMap(properties)) return schema
    return {
        ...schema,
        properties: Object.fromEntries(
            Object.entries(properties).map(([name, one]) => [
                name,
                secrets.includes(name) && isMap(one) ? { ...one, writeOnly: true } : one,
            ]),
        ),
    }
}

/** An empty object schema, for a form with nothing behind it yet. */
const EMPTY: JsonSchema = { type: 'object', properties: {} }

/**
 * The schema a form is drawn from: labeled by key, its secrets write-only, and locked whole
 * where nothing on it may be edited.
 */
export function formSchema(
    schema: JsonMap | null | undefined,
    { secrets = [], locked = false }: { secrets?: readonly string[]; locked?: boolean } = {},
): JsonSchema {
    if (schema === null || schema === undefined) return EMPTY
    const drawn = sealedFields(untitled(schema), secrets) as JsonSchema
    return locked ? { ...drawn, readOnly: true } : drawn
}

/** Whether a form's schema draws any field at all. */
export function hasFields(schema: JsonSchema): boolean {
    return Object.keys(schema.properties ?? {}).length > 0
}

/** A value written as `${...}`, which the run resolves and no check here may refuse. */
export const deferReference: DeferredValue = (value) => hasReference(value)

/** How the library draws a schema: fields, rows, key/value rows, one control, or JSON text. */
type LibraryKind = 'object' | 'list' | 'map' | 'scalar' | 'longtext' | 'json'

/** The library's own reading of a schema, which decides what it can draw and what it leaves as JSON. */
function libraryKind(schema: JsonSchema, root: JsonSchema): LibraryKind {
    const main = types(schema).main
    if (schema.properties !== undefined) return 'object'
    if (main[0] === 'array' && schema.items !== undefined) {
        const items = fieldSchema(schema.items, root)
        if (items.enum !== undefined || items.properties !== undefined) return 'list'
        const kind = libraryKind(items, root)
        return kind === 'json' || kind === 'object' || kind === 'map' ? 'json' : 'list'
    }
    if (typeof schema.additionalProperties === 'object' && (main.length === 0 || main[0] === 'object'))
        return libraryKind(fieldSchema(schema.additionalProperties, root), root) === 'scalar' ? 'map' : 'json'
    if (schema.enum !== undefined || scalarUnion(schema, root) !== undefined) return 'scalar'
    if (main.length !== 1) return 'json'
    if (main[0] === 'string')
        return (schema.maxLength ?? 0) > 200 ||
            schema.format === 'markdown' ||
            schema.contentMediaType !== undefined
            ? 'longtext'
            : 'scalar'
    return main[0] === 'boolean' || main[0] === 'number' || main[0] === 'integer' ? 'scalar' : 'json'
}

/**
 * How dirigent draws a field the form hands it: a program, a JSON value, text, a value whose own
 * control (a number, a choice, a switch) cannot hold text, or `other` for the form's own fields,
 * rows and key/value rows.
 */
export type DrawnAs = 'program' | 'json' | 'text' | 'value' | 'other'

/** How one field's resolved schema is drawn, its references read against `root`. */
export function drawnAs(schema: JsonSchema, root: JsonSchema = schema): DrawnAs {
    const main = types(schema).main
    if (typeof schema.contentMediaType === 'string' && main.length === 1 && main[0] === 'string')
        return 'program'
    if (schema.enum !== undefined || schema.const !== undefined) return 'value'
    switch (libraryKind(schema, root)) {
        case 'json':
            return 'json'
        case 'object':
        case 'list':
        case 'map':
            return 'other'
        case 'longtext':
            return 'text'
        case 'scalar':
            return main.length === 1 && main[0] !== 'string' ? 'value' : 'text'
    }
}

/** What a field's schema says its value names, from `x-dirigent-ref`, or null. */
export function refersTo(schema: JsonSchema): ReferenceKind | null {
    const named = schema[REFERENCE_KEYWORD]
    return named === 'connection' || named === 'schema' ? named : null
}

/**
 * The text a JSON buffer shows: what was typed while it does not parse or still reads as the
 * value, else the value written out.
 */
export function readJson(draft: string | undefined, value: unknown): string {
    const written = value === undefined ? '' : (JSON.stringify(value, null, 2) ?? '')
    if (draft === undefined) return written
    if (draft.trim() === '') return value === undefined ? draft : written
    try {
        return sameJson(JSON.parse(draft) as unknown, value) ? draft : written
    } catch {
        return draft
    }
}
