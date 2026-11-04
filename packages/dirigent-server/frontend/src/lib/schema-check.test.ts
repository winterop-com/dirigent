import { describe, expect, test } from 'vitest'

import {
    checkInput,
    holdsStored,
    marksOf,
    sampleOf,
    sampleText,
    shownCheck,
    spanAt,
    spansOf,
    type CheckAnswer,
    type SchemaCheck,
} from '@/lib/schema-check'
import { draftOf, holdDraft, schemaDrafts } from '@/lib/schemas'

const SCHEMA = '{"type": "object", "required": ["id"]}'

const FAILED: SchemaCheck = {
    valid: false,
    errors: [
        {
            at: '/age',
            keyword: 'minimum',
            schema_at: '/properties/age/minimum',
            message: '-1 is less than 0',
        },
    ],
    omitted: 0,
}

describe('what the two editors hold', () => {
    test('is sent when both are JSON and the schema is an object', () => {
        expect(checkInput(SCHEMA, 'null')).toEqual({
            kind: 'ready',
            body: { type: 'object', required: ['id'] },
            value: null,
        })
    })

    test('says which one is not JSON, the schema before the value', () => {
        const both = checkInput('{', '[')
        expect(both.kind === 'unreadable' && both.which).toBe('schema')
        const value = checkInput(SCHEMA, '{"a": }')
        expect(value.kind === 'unreadable' && value.which).toBe('value')
        expect(value.kind === 'unreadable' && value.sentence).toMatch(/^The value is not readable JSON: /)
    })

    test('refuses a schema that is JSON but not an object, which no check takes', () => {
        const read = checkInput('[]', '{}')
        expect(read).toEqual({
            kind: 'unreadable',
            which: 'schema',
            sentence: 'The schema is not an object.',
        })
    })
})

describe('what the result says', () => {
    const ready = checkInput(SCHEMA, '{}')
    const answer: CheckAnswer = { kind: 'checked', check: FAILED, schema: SCHEMA, value: '{}' }

    test('is the unreadable sentence at once, whatever answered last', () => {
        expect(shownCheck(checkInput('{', '{}'), answer, '{', '{}').kind).toBe('unreadable')
    })

    test('is checking until the first answer lands', () => {
        expect(shownCheck(ready, null, SCHEMA, '{}')).toEqual({ kind: 'checking' })
    })

    test('keeps the last answer while the next is asked, saying it is not about the text on screen', () => {
        expect(shownCheck(ready, answer, SCHEMA, '{}')).toEqual({
            kind: 'checked',
            check: FAILED,
            current: true,
        })
        expect(shownCheck(checkInput(SCHEMA, '{ }'), answer, SCHEMA, '{ }')).toEqual({
            kind: 'checked',
            check: FAILED,
            current: false,
        })
    })
})

describe('where a pointer is in the value', () => {
    const text = '{\n  "id": "a",\n  "tags": ["x", 3],\n  "a/b~c": {"deep": true}\n}'

    test('is found for every value, under the pointer the server writes', () => {
        const spans = spansOf(text)
        const tag = spans.get('/tags/1')
        expect(tag && text.slice(tag.start, tag.end)).toBe('3')
        const member = spans.get('/id')
        expect(member && text.slice(member.start, member.end)).toBe('"id": "a"')
        const escaped = spans.get('/a~1b~0c/deep')
        expect(escaped && text.slice(escaped.start, escaped.end)).toBe('"deep": true')
        expect(spans.get('')?.start).toBe(0)
    })

    test('falls back to the nearest place the text holds, for a member that is missing', () => {
        const spans = spansOf(text)
        expect(spanAt(spans, '/tags/9')).toEqual(spans.get('/tags'))
        expect(spanAt(spans, '/missing')).toEqual(spans.get(''))
    })

    test('marks a container by its opening rather than the whole of it', () => {
        const [mark] = marksOf(text, [{ at: '/a~1b~0c', keyword: 'type', schema_at: '', message: 'no' }])
        expect(mark && text.slice(mark.start, mark.end)).toBe('"a/b~c": {')
        expect(mark?.message).toBe('no')
    })
})

describe('the value a tester starts from', () => {
    test('is the first example, else the default, else the const', () => {
        expect(sampleOf({ examples: [{ id: 'a' }, { id: 'b' }], default: 1 })).toEqual({ id: 'a' })
        expect(sampleOf({ default: 3, const: 4 })).toBe(3)
        expect(sampleOf({ const: 4 })).toBe(4)
    })

    test('is built from what the schema asks for where it offers no example', () => {
        const schema = {
            type: 'object',
            $defs: { unit: { type: 'string', enum: ['kg', 'g'] } },
            properties: {
                id: { examples: ['ou-1'] },
                level: { type: 'integer', minimum: 2 },
                weight: { type: 'number', exclusiveMinimum: 0, maximum: 10 },
                unit: { $ref: '#/$defs/unit' },
                seen: { type: 'string', format: 'date-time' },
                code: { type: 'string', minLength: 3 },
                tags: { type: 'array', items: { type: 'string' }, minItems: 2 },
                active: { type: 'boolean' },
                either: { anyOf: [{ type: 'null' }, { type: 'string' }] },
            },
        }
        expect(sampleOf(schema)).toEqual({
            id: 'ou-1',
            level: 2,
            weight: 0.5,
            unit: 'kg',
            seen: '2026-01-01T12:00:00Z',
            code: 'xxx',
            tags: ['', ''],
            active: false,
            either: null,
        })
    })

    test('matches a simple pattern, and leaves one beyond it empty', () => {
        expect(sampleOf({ type: 'string', pattern: '^[A-Z]{3}[0-9]{2}$' })).toBe('AAA00')
        expect(sampleOf({ type: 'string', pattern: '^OU-\\d+$' })).toBe('OU-0')
        expect(sampleOf({ type: 'string', pattern: '^[a-z][a-z0-9-]{0,10}$' })).toBe('a')
        expect(sampleOf({ type: 'string', pattern: '^(a|b)$' })).toBe('')
    })

    test('is an empty object for an object schema with no properties', () => {
        expect(sampleOf({ type: 'object' })).toEqual({})
        expect(sampleText({ type: 'object' })).toBe('{}')
    })
})

describe('whether the schema editor holds what is stored', () => {
    test('reads the shape, not its layout or its key order', () => {
        expect(holdsStored('{"b": 1,\n "a": [1, {"y": 2, "x": 1}]}', { a: [1, { x: 1, y: 2 }], b: 1 })).toBe(
            true,
        )
        expect(holdsStored('{"a": 2}', { a: 1 })).toBe(false)
        expect(holdsStored('{', { a: 1 })).toBe(false)
    })
})

describe('a schema typed and not saved', () => {
    test('is what an editor opens on until it says what is stored again', () => {
        schemaDrafts.set({})
        holdDraft('reading', '{"x": 1}', '{}')
        expect(draftOf('reading', '{}')).toBe('{"x": 1}')
        holdDraft('reading', '{}', '{}')
        expect(draftOf('reading', '{}')).toBe('{}')
        expect(schemaDrafts.get()).toEqual({})
    })
})
