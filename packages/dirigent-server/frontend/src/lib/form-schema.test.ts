import { describe, expect, test } from 'vitest'

import type { JsonMap } from '@/lib/api'
import {
    deferReference,
    drawnAs,
    formSchema,
    hasFields,
    heldAs,
    readJson,
    refersTo,
    untitled,
} from '@/lib/form-schema'

/** A connection kind's published config schema, shaped the way pydantic writes one. */
const SCHEMA: JsonMap = {
    title: 'HttpConfig',
    type: 'object',
    $defs: { Method: { title: 'Method', type: 'string', enum: ['GET', 'POST'] } },
    properties: {
        base_url: { title: 'Base Url', type: 'string' },
        basic_password: {
            anyOf: [{ type: 'string', format: 'password', writeOnly: true }, { type: 'null' }],
            default: null,
            title: 'Basic Password',
        },
        bearer_token: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null },
        method: { $ref: '#/$defs/Method' },
        title: { type: 'string', title: 'Title' },
    },
    required: ['base_url'],
}

describe('the schema a form is drawn from', () => {
    test('labels every field by its key: no title is left, at any depth', () => {
        expect(JSON.stringify(untitled(SCHEMA))).not.toContain('"title":"')
    })

    test('keeps a field named title, which is a key and not the keyword', () => {
        expect(Object.keys(untitled(SCHEMA).properties as JsonMap)).toContain('title')
    })

    test('marks every field the kind declares secret write-only', () => {
        const drawn = formSchema(SCHEMA, { secrets: ['bearer_token'] })
        expect(drawn.properties?.bearer_token.writeOnly).toBe(true)
        expect(drawn.properties?.base_url.writeOnly).toBeUndefined()
    })

    test('locks every field where nothing may be edited', () => {
        expect(formSchema(SCHEMA, { locked: true }).readOnly).toBe(true)
        expect(formSchema(SCHEMA).readOnly).toBeUndefined()
    })

    test('has no fields before a kind has been chosen, because no schema is known yet', () => {
        expect(hasFields(formSchema(null))).toBe(false)
        expect(hasFields(formSchema(SCHEMA))).toBe(true)
    })
})

describe('how a field is drawn', () => {
    test('a string carrying a media type is a program', () => {
        expect(drawnAs({ type: 'string', contentMediaType: 'application/jq' })).toBe('program')
    })

    test('what the library can only take as JSON text is JSON', () => {
        expect(drawnAs({})).toBe('json')
        expect(drawnAs({ anyOf: [{ type: 'string' }, { type: 'object' }] })).toBe('json')
        expect(drawnAs({ type: 'object', additionalProperties: { type: 'object' } })).toBe('json')
        expect(drawnAs({ type: 'array', items: { type: 'object' } })).toBe('json')
    })

    test('a union of scalars is text, read as the narrowest branch it parses as', () => {
        const size = {
            anyOf: [{ type: 'string', pattern: '^\\d+[KMG]?B$' }, { type: 'integer' }],
            format: 'size',
        }
        expect(drawnAs(size)).toBe('text')
        expect(drawnAs({ type: ['string', 'integer'] })).toBe('text')
    })

    test('a number, a switch and a choice are values their control cannot hold text in', () => {
        expect(drawnAs({ type: 'integer' })).toBe('value')
        expect(drawnAs({ type: 'boolean' })).toBe('value')
        expect(drawnAs({ type: 'string', enum: ['a', 'b'] })).toBe('value')
    })

    test("an object with fields, a list and a map of scalars are the form's own", () => {
        expect(drawnAs({ type: 'object', properties: {} })).toBe('other')
        expect(drawnAs({ type: 'array', items: { type: 'string' } })).toBe('other')
        expect(drawnAs({ type: 'object', additionalProperties: { type: 'string' } })).toBe('other')
    })

    test('a map whose values are named by reference is read against the root', () => {
        const root = { $defs: { Level: { type: 'string', enum: ['a', 'b'] } } }
        const map = { type: 'object', additionalProperties: { $ref: '#/$defs/Level' } }
        expect(drawnAs(map, root)).toBe('other')
    })

    test('a control that cannot hold a reference is named; one that can is null', () => {
        expect(heldAs({ type: 'string', enum: ['a', 'b'] })).toBe('choice')
        expect(heldAs({ type: 'boolean' })).toBe('switch')
        expect(heldAs({ type: 'integer' })).toBe('number')
        expect(heldAs({ type: 'object', additionalProperties: { type: 'string' } })).toBe('map')
        expect(heldAs({ type: 'array', items: { type: 'string' } })).toBe('list')
        expect(heldAs({ type: 'object', properties: {} })).toBe('object')
        expect(heldAs({ type: 'string' })).toBeNull()
        expect(heldAs({ type: ['string', 'integer'] })).toBeNull()
        expect(heldAs({})).toBeNull()
    })

    test('a string that names a connection or a schema says which', () => {
        expect(refersTo({ type: 'string', 'x-dirigent-ref': 'schema' })).toBe('schema')
        expect(refersTo({ type: 'string', 'x-dirigent-ref': 'connection' })).toBe('connection')
        expect(refersTo({ type: 'string', 'x-dirigent-ref': 'pipeline' })).toBeNull()
    })
})

describe('the text a JSON buffer shows', () => {
    test('is the value written out when nothing was typed', () => {
        expect(readJson(undefined, { a: 1 })).toBe('{\n  "a": 1\n}')
        expect(readJson(undefined, undefined)).toBe('')
    })

    test('is what was typed while it does not parse, or still reads as the value', () => {
        expect(readJson('{"a": ', { a: 1 })).toBe('{"a": ')
        expect(readJson('{"a":1}', { a: 1 })).toBe('{"a":1}')
    })

    test('is the value once it was changed elsewhere', () => {
        expect(readJson('{"a":1}', { a: 2 })).toBe('{\n  "a": 2\n}')
    })
})

describe('a value written as a reference', () => {
    test('is left unchecked, and the escape is not one', () => {
        expect(deferReference('${params.rows}')).toBe(true)
        expect(deferReference('$${params.rows}')).toBe(false)
        expect(deferReference(3)).toBe(false)
    })
})
