import { describe, expect, test } from 'vitest'

import { ApiError, type Issue, type Problem } from '@/lib/api'
import { local, refusalLine, refusalLines, refusalOf, said } from '@/lib/refusal'
import { contributedWording } from '@/lib/wording'

/** One refusal as this server writes it: a status phrase for a title, and a sentence to act on. */
function problem(over: Partial<Problem> = {}): Problem {
    return {
        status: 422,
        title: 'Unprocessable Content',
        detail: 'the document was refused',
        code: 'document.unsatisfied',
        params: {},
        problems: [],
        instance: '/api/v1/pipelines/$apply',
        ...over,
    }
}

/** One issue as the server writes it, addressed at the place in the document that is wrong. */
function issue(location: string, message: string): Issue {
    return { code: 'document.step_config_invalid', message, params: {}, location }
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
            code: 'client.no_answer',
            params: {},
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
            problem({ detail: 'the document was refused', problems: [issue('steps.a', 'unknown block')] }),
        )
        expect(lines).toEqual({ detail: 'the document was refused', problems: ['steps.a: unknown block'] })
    })

    test('a sentence that is the failures joined is not said twice', () => {
        const listed = [issue('steps.a', 'unknown block'), issue('steps.b', 'depends on nothing')]
        const drawn = ['steps.a: unknown block', 'steps.b: depends on nothing']
        expect(refusalLines(problem({ detail: drawn.join('; '), problems: listed }))).toEqual({
            detail: null,
            problems: drawn,
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
        const listed = [issue('a', 'no'), issue('b', 'no')]
        expect(refusalLine(problem({ detail: 'a: no; b: no', problems: listed }))).toBe('a: no; b: no')
    })
})

describe('whose sentence a refusal is drawn in', () => {
    test('a code this interface has a sentence for is drawn in that sentence', () => {
        // The server's `detail` is a lower-case fragment; what is drawn is this bundle's own.
        const refused = problem({
            code: 'server.no_run',
            params: { run_id: '01a0eeba' },
            detail: 'no run 01a0eeba',
        })
        expect(said(refused)).toBe('No run 01a0eeba.')
    })

    test('a code it has no sentence for falls back to the one the server sent', () => {
        // `document.step_config_invalid` is the server's `{detail}`: it carries no words of its
        // own, so the sentence it sent is already the right rendering.
        expect(said(problem({ code: 'document.step_config_invalid', detail: 'method is unknown' }))).toBe(
            'method is unknown',
        )
    })

    test('a sentence naming a value the refusal does not carry falls back rather than drawing a hole', () => {
        const refused = problem({ code: 'server.no_run', params: {}, detail: 'no run 01a0eeba' })
        expect(said(refused)).toBe('no run 01a0eeba')
    })

    test("a pack's contributed sentence is drawn once the instance has been asked for it", () => {
        const refused = problem({
            code: 'dhis2.answered',
            params: { where: 'POST /api/dataValueSets', status: 409, remote: 'in progress' },
            detail: 'POST /api/dataValueSets answered 409: in progress',
        })
        expect(said(refused)).toBe('POST /api/dataValueSets answered 409: in progress')
        contributedWording.set({ 'dhis2.answered': '{where} was refused with {status}: {remote}' })
        expect(said(refused)).toBe('POST /api/dataValueSets was refused with 409: in progress')
        contributedWording.set({})
    })

    test('a failure in the list is drawn in this interface sentence too', () => {
        const listed: Issue = {
            code: 'pipeline.unknown',
            message: 'no pipeline coded convert-one',
            params: { code: 'convert-one' },
            location: 'steps.a',
        }
        expect(refusalLines(problem({ detail: 'refused', problems: [listed] })).problems).toEqual([
            'steps.a: No pipeline coded convert-one.',
        ])
    })

    test('the list is still said once when re-rendering changed its words', () => {
        const listed: Issue = {
            code: 'pipeline.unknown',
            message: 'no pipeline coded convert-one',
            params: { code: 'convert-one' },
            location: null,
        }
        // `detail` is the server's joining of what it sent, which no longer matches what is drawn.
        const lines = refusalLines(problem({ detail: 'no pipeline coded convert-one', problems: [listed] }))
        expect(lines).toEqual({ detail: null, problems: ['No pipeline coded convert-one.'] })
    })
})
