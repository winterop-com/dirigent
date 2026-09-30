import { describe, expect, test } from 'vitest'

import {
    bodyText,
    schemaPatch,
    schemasNote,
    validatedBy,
    wholeSchema,
    whyKept,
    type SchemaOut,
} from '@/lib/schemas'

const STORED: SchemaOut = {
    id: '9f2a4c1e-0000-4000-8000-000000000001',
    code: 'org-unit',
    name: 'Organisation unit',
    description: 'The shape the org-unit read returns.',
    body: { $id: 'org-unit', title: 'Organisation unit', type: 'object' },
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-09-01T10:00:00Z',
    used_by: [],
}

describe('the text a stored schema is opened in', () => {
    test('is the body indented, so a shape is read on the lines it was written on', () => {
        expect(bodyText(STORED)).toBe(JSON.stringify(STORED.body, null, 2))
        expect(bodyText(STORED)).toContain('\n  "title"')
    })
})

describe('what one edit sends', () => {
    test('sends nothing at all where nothing changed', () => {
        expect(schemaPatch(STORED, STORED.name, STORED.description, undefined)).toBeNull()
    })

    test('sends only the member that moved', () => {
        expect(schemaPatch(STORED, 'Org unit', STORED.description, undefined)).toEqual({
            name: 'Org unit',
        })
    })

    test('clears a label a box was emptied of, rather than storing an empty string', () => {
        expect(schemaPatch(STORED, null, STORED.description, undefined)).toEqual({ name: null })
    })

    test('sends the body only where the text was edited', () => {
        const body = { $id: 'org-unit', type: 'object', required: ['id'] }
        expect(schemaPatch(STORED, STORED.name, STORED.description, body)).toEqual({ body })
    })

    test('sends every member that moved in one request', () => {
        const body = { type: 'string' }
        expect(schemaPatch(STORED, 'Unit', null, body)).toEqual({
            name: 'Unit',
            description: null,
            body,
        })
    })
})

describe('replacing a stored schema with one written elsewhere', () => {
    /**
     * A create reads `title` and `description` off the schema and an update reads neither, so
     * the identity has to travel with the body or the instance keeps the labels of a shape it no
     * longer holds.
     */
    test('carries the identity the schema declares', () => {
        expect(wholeSchema({ title: 'Field unit', description: 'One unit.', type: 'object' })).toEqual({
            body: { title: 'Field unit', description: 'One unit.', type: 'object' },
            name: 'Field unit',
            description: 'One unit.',
        })
    })

    test('clears a label the schema does not declare', () => {
        expect(wholeSchema({ type: 'object' })).toEqual({
            body: { type: 'object' },
            name: null,
            description: null,
        })
    })

    test('reads no label out of a keyword that is not a string', () => {
        expect(wholeSchema({ title: 3, description: ['a'] })).toEqual({
            body: { title: 3, description: ['a'] },
            name: null,
            description: null,
        })
    })
})

describe('what the screen says it holds', () => {
    test('counts the rows read, singular where there is one of them', () => {
        expect(schemasNote([])).toBeNull()
        expect(schemasNote([STORED])).toBe('1 schema')
        expect(schemasNote([STORED, { ...STORED, code: 'field-unit' }])).toBe('2 schemas')
    })
})

describe('what a stored schema says about the pipelines naming it', () => {
    test('a shape nothing names is freely removed and says nothing about dependants', () => {
        expect(whyKept(STORED)).toBeUndefined()
        expect(validatedBy(STORED)).toBeNull()
    })

    test('a shape one pipeline names shuts the delete and names the pipeline', () => {
        const held = { ...STORED, used_by: ['nightly'] }
        expect(whyKept(held)).toBe('nightly names this shape, so it cannot be removed.')
        expect(validatedBy(held)).toBe('nightly validates against this shape.')
    })

    test('several pipelines are listed in the order the server gave them', () => {
        const held = { ...STORED, used_by: ['nightly', 'weekly'] }
        expect(whyKept(held)).toBe('nightly, weekly name this shape, so it cannot be removed.')
        expect(validatedBy(held)).toBe('nightly, weekly validate against this shape.')
    })
})
