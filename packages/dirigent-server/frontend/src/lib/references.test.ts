import { describe, expect, test } from 'vitest'

import type { ConnectionOut } from '@/lib/connections'
import { carriedSchemas, codeNamed, resolveConnection, resolveSchema } from '@/lib/references'
import type { SchemaOut } from '@/lib/schemas'

const STORED: SchemaOut = {
    id: '1b0f1e2c-0000-4000-8000-000000000001',
    code: 'ou-record',
    name: 'Organisation unit',
    description: null,
    body: { type: 'object', properties: { id: { type: 'string' } } },
    created_at: '2026-09-01T09:00:00Z',
    updated_at: '2026-09-01T09:00:00Z',
}

const CONNECTION: ConnectionOut = {
    id: '1b0f1e2c-0000-4000-8000-000000000002',
    code: 'dhis2-demo',
    name: null,
    kind: 'http',
    description: null,
    config: { base_url: 'https://play.example' },
    secret_fields: ['password'],
    last_check_at: null,
    last_check_healthy: null,
    last_check_detail: null,
    created_at: '2026-09-01T09:00:00Z',
    updated_at: '2026-09-01T09:00:00Z',
}

/** The carried form, as a document writes it: a top-level section keyed by code. */
const CARRYING = {
    schemas: { 'ou-record': { type: 'object', required: ['id'] } },
    steps: { check: { block: 'validate.schema', config: { schema: 'ou-record' } } },
}

describe('the code a field value names', () => {
    test('a code is the text it was written as, without the whitespace around it', () => {
        expect(codeNamed('ou-record')).toBe('ou-record')
        expect(codeNamed('  ou-record  ')).toBe('ou-record')
    })

    test('an empty box and a value that is not text name nothing', () => {
        expect(codeNamed('')).toBeNull()
        expect(codeNamed('   ')).toBeNull()
        expect(codeNamed(undefined)).toBeNull()
        expect(codeNamed(null)).toBeNull()
        expect(codeNamed(7)).toBeNull()
    })

    test('a reference names nothing, whether it is the whole value or part of one', () => {
        expect(codeNamed('${params.shape}')).toBeNull()
        expect(codeNamed('ou-${params.level}')).toBeNull()
    })
})

describe('what a schema code resolves to', () => {
    test('the document carries it, which is what the run will read', () => {
        expect(resolveSchema(CARRYING, 'ou-record', [STORED])).toEqual({
            source: 'carried',
            body: { type: 'object', required: ['id'] },
        })
    })

    test('the instance holds it, when the document carries no shape of that name', () => {
        expect(resolveSchema({ steps: {} }, 'ou-record', [STORED])).toEqual({
            source: 'instance',
            schema: STORED,
        })
    })

    test('nothing holds it, once the listing has landed', () => {
        expect(resolveSchema(null, 'ou-record', [])).toEqual({ source: 'missing' })
    })

    test('a listing nobody has read yet is not an empty one', () => {
        expect(resolveSchema(null, 'ou-record', null)).toEqual({ source: 'unread' })
    })

    test('a carried shape answers before the listing has been read at all', () => {
        expect(resolveSchema(CARRYING, 'ou-record', null).source).toBe('carried')
    })

    test('a schemas section that is not a map of bodies carries nothing', () => {
        expect(carriedSchemas({ schemas: ['ou-record'] })).toEqual({})
        expect(carriedSchemas({ schemas: { 'ou-record': 'a string' } })).toEqual({})
        expect(carriedSchemas(null)).toEqual({})
    })
})

describe('what a connection code resolves to', () => {
    test('the instance holds it', () => {
        expect(resolveConnection('dhis2-demo', [CONNECTION])).toEqual({
            source: 'instance',
            connection: CONNECTION,
        })
    })

    test('nothing holds it, once the listing has landed', () => {
        expect(resolveConnection('dhis2-demo', [])).toEqual({ source: 'missing' })
    })

    test('a listing nobody has read yet is not an empty one', () => {
        expect(resolveConnection('dhis2-demo', null)).toEqual({ source: 'unread' })
    })
})
