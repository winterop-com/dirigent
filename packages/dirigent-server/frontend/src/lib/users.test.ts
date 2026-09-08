import { describe, expect, test } from 'vitest'

import { accountHeading } from '@/lib/users'

describe('an account is headed by the same rule as everything else', () => {
    test('the name is the title, and the username stays on screen as the code', () => {
        const heading = accountHeading({ username: 'ada', name: 'Ada Lovelace' })
        expect(heading.title).toBe('Ada Lovelace')
        expect(heading.code).toBe('ada')
        expect(heading.named).toBe(true)
    })

    test('an account with no name is titled by what it signs in as, and the code is not drawn twice', () => {
        const heading = accountHeading({ username: 'ada', name: null })
        expect(heading.title).toBe('ada')
        expect(heading.code).toBeNull()
        expect(heading.named).toBe(false)
    })

    // REVERT-PROOF. `name ?? username` passes every test above and fails this one: a name of
    // whitespace is a title nobody can read, over a username nothing would then draw.
    test('a name of whitespace is not a name', () => {
        const heading = accountHeading({ username: 'ada', name: '   ' })
        expect(heading.title).toBe('ada')
        expect(heading.code).toBeNull()
    })
})
