import { describe, expect, test } from 'vitest'

import { ApiError, type Problem } from '@/lib/api'
import { formProblem, NO_PASSWORD, passwordBody, refusalOf } from '@/lib/password'
import { MIN_PASSWORD_LENGTH } from '@/lib/users'

/** What the server refuses a wrong current password with, verbatim. */
const WRONG: Problem = {
    status: 403,
    title: 'Forbidden',
    detail: 'the current password is not correct',
    problems: [],
    instance: '/api/v1/auth/password',
}

const GOOD = { current: 'old-password', next: 'new-password' }

describe('the body sent to change a password', () => {
    test("uses the wire's own member names", () => {
        expect(passwordBody(GOOD)).toEqual({ current_password: 'old-password', new_password: 'new-password' })
    })

    test('carries nothing the form held that the API did not ask for', () => {
        expect(Object.keys(passwordBody(GOOD))).toEqual(['current_password', 'new_password'])
    })
})

describe('what the form refuses without asking the server', () => {
    test('an empty form, because there is nothing to ask', () => {
        expect(formProblem(NO_PASSWORD)?.detail).toContain('signs in with now')
    })

    test('a new password shorter than this server accepts', () => {
        const short = 'a'.repeat(MIN_PASSWORD_LENGTH - 1)
        expect(formProblem({ current: 'old-password', next: short })?.detail).toContain(
            String(MIN_PASSWORD_LENGTH),
        )
    })

    test('a new password that is the old one, which changes nothing', () => {
        expect(formProblem({ current: 'old-password', next: 'old-password' })).not.toBeNull()
    })

    test('nothing, when there is a request to make', () => {
        expect(formProblem(GOOD)).toBeNull()
    })

    test('a local refusal wears the shape every refusal in this app wears', () => {
        const problem = formProblem(NO_PASSWORD)
        expect(problem).not.toBeNull()
        expect(problem?.problems).toEqual([])
        expect(typeof problem?.title).toBe('string')
    })
})

describe('what a refused change leaves on screen', () => {
    // REVERT-PROOF: the wrong-password refusal is 403, and the sentence on screen is the one the
    // server wrote. Summarise it here and this fails.
    test("is the server's own problem document, unchanged", () => {
        expect(refusalOf(new ApiError(WRONG))).toEqual(WRONG)
        expect(refusalOf(new ApiError(WRONG)).detail).toBe('the current password is not correct')
    })

    test("is a sentence of this app's when nothing answered at all", () => {
        const problem = refusalOf(new TypeError('network down'))
        expect(problem.status).toBe(0)
        expect(problem.detail).toContain('has not been changed')
    })
})
