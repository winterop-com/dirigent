import { describe, expect, test } from 'vitest'

import { contributedWording, fill, sentenceFor } from '@/lib/wording'

describe('writing a refusal params into a sentence', () => {
    test('a named hole takes the value of that name', () => {
        expect(fill('No run {run_id}.', { run_id: '01a0eeba' })).toBe('No run 01a0eeba.')
    })

    test('a value that is not a string is written as one', () => {
        expect(fill('{where} answered {status}', { where: 'POST /x', status: 409 })).toBe(
            'POST /x answered 409',
        )
    })

    test('the same hole twice is filled twice', () => {
        expect(fill('{username}/{username}', { username: 'demo' })).toBe('demo/demo')
    })

    test('a sentence with no holes needs no params', () => {
        expect(fill('Invalid username or password.', {})).toBe('Invalid username or password.')
    })

    test('a hole the refusal does not carry refuses the whole sentence', () => {
        // Drawing `{run_id}` at a person is worse than drawing the English the server sent.
        expect(fill('No run {run_id}.', {})).toBeNull()
        expect(fill('No run {run_id}.', { run_id: null })).toBeNull()
    })
})

describe('which table a code is said out of', () => {
    test("this bundle's own sentence, for a code the instance mints", () => {
        expect(sentenceFor('pipeline.unknown', { code: 'convert-one' })).toBe(
            'No pipeline coded convert-one.',
        )
    })

    test('nothing, for a code neither table holds', () => {
        expect(sentenceFor('acme.nothing_here', {})).toBeNull()
    })

    test('nothing, for a refusal that arrived under no code at all', () => {
        expect(sentenceFor('', {})).toBeNull()
    })

    test("the instance's, for a code a pack contributed", () => {
        expect(sentenceFor('acme.too_many', { count: '9' })).toBeNull()
        contributedWording.set({ 'acme.too_many': '{count} is too many.' })
        expect(sentenceFor('acme.too_many', { count: '9' })).toBe('9 is too many.')
        contributedWording.set({})
    })

    test("this bundle's own wins, so a pack cannot reword the instance's refusals", () => {
        contributedWording.set({ 'pipeline.unknown': 'Something else entirely.' })
        expect(sentenceFor('pipeline.unknown', { code: 'convert-one' })).toBe(
            'No pipeline coded convert-one.',
        )
        contributedWording.set({})
    })
})
