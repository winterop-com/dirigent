import { describe, expect, test } from 'vitest'

import { ApiError, type Problem } from '@/lib/api'
import { local, refusalLine, refusalLines, refusalOf } from '@/lib/refusal'

/** One refusal as this server writes it: a status phrase for a title, and a sentence to act on. */
function problem(over: Partial<Problem> = {}): Problem {
    return {
        status: 422,
        title: 'Unprocessable Content',
        detail: 'the document was refused',
        problems: [],
        instance: '/api/v1/pipelines/$apply',
        ...over,
    }
}

describe('what a refusal is made of', () => {
    test('an ApiError carries the document the server refused with', () => {
        const refused = problem()
        expect(refusalOf(new ApiError(refused))).toBe(refused)
    })

    test('anything else is the one sentence there is to say about it', () => {
        expect(refusalOf(new Error('socket hang up')).detail).toBe('The server did not answer.')
    })

    test('a refusal this bundle made carries no status phrase', () => {
        expect(local('That is not JSON.')).toEqual({
            status: 0,
            title: '',
            detail: 'That is not JSON.',
            problems: [],
            instance: null,
        })
    })
})

describe('which parts of a refusal are worth drawing', () => {
    test('a sentence with no failures under it is the whole of it', () => {
        expect(refusalLines(problem())).toEqual({ detail: 'the document was refused', problems: [] })
    })

    test('failures that say more than the sentence are drawn beside it', () => {
        const lines = refusalLines(
            problem({ detail: 'the document was refused', problems: ['steps.a: unknown block'] }),
        )
        expect(lines).toEqual({ detail: 'the document was refused', problems: ['steps.a: unknown block'] })
    })

    test('a sentence that is the failures joined is not said twice', () => {
        const listed = ['steps.a: unknown block', 'steps.b: depends on nothing']
        expect(refusalLines(problem({ detail: listed.join('; '), problems: listed }))).toEqual({
            detail: null,
            problems: listed,
        })
    })

    test('an empty sentence is nothing rather than an empty line', () => {
        expect(refusalLines(problem({ detail: '   ' })).detail).toBeNull()
    })
})

describe('a refusal in one line', () => {
    test('the sentence, where there is one', () => {
        expect(refusalLine(problem())).toBe('the document was refused')
    })

    test('the failures, where the sentence is only their joining', () => {
        const listed = ['a: no', 'b: no']
        expect(refusalLine(problem({ detail: listed.join('; '), problems: listed }))).toBe('a: no; b: no')
    })
})
