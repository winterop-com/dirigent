import { describe, expect, test } from 'vitest'

import { accountHeading, isLive, revokedTogether, sharedNames, tokenCounts, type TokenOut } from '@/lib/users'

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

const NOW = Date.parse('2026-06-01T00:00:00Z')

function token(name: string, over: Partial<TokenOut> = {}): TokenOut {
    return {
        id: name,
        name,
        username: 'ada',
        prefix: 'k7Qx2mPa',
        created_at: '2026-01-01T00:00:00Z',
        last_used_at: null,
        expires_at: null,
        revoked_at: null,
        ...over,
    }
}

describe('whether a token is live', () => {
    test('is whether it has neither been revoked nor run out', () => {
        expect(isLive(token('a'), NOW)).toBe(true)
        expect(isLive(token('a', { revoked_at: '2026-02-01T00:00:00Z' }), NOW)).toBe(false)
        expect(isLive(token('a', { expires_at: '2026-02-01T00:00:00Z' }), NOW)).toBe(false)
        expect(isLive(token('a', { expires_at: '2027-02-01T00:00:00Z' }), NOW)).toBe(true)
    })
})

describe('when a prefix is worth drawing', () => {
    test('is never for names that tell their tokens apart', () => {
        expect(sharedNames([token('a'), token('b')], NOW).size).toBe(0)
    })

    test('is for a name two live tokens share', () => {
        expect(sharedNames([token('a'), token('a'), token('b')], NOW)).toEqual(new Set(['a']))
    })

    // REVERT-PROOF. A token that can no longer authenticate is not one to tell apart from anything.
    test('is not for a name only one live token still carries', () => {
        const revoked = token('a', { revoked_at: '2026-02-01T00:00:00Z' })
        const expired = token('a', { expires_at: '2026-02-01T00:00:00Z' })
        expect(sharedNames([token('a'), revoked, expired], NOW).size).toBe(0)
    })
})

describe('how many tokens a revoke takes', () => {
    test('is every one of that name not yet revoked, because the API revokes by name', () => {
        const tokens = [
            token('a'),
            token('a', { expires_at: '2026-02-01T00:00:00Z' }),
            token('a', { revoked_at: '2026-02-01T00:00:00Z' }),
            token('b'),
        ]
        expect(revokedTogether(tokens, 'a')).toBe(2)
    })
})

describe('how many live tokens each account holds', () => {
    test('counts by account and leaves out what can no longer authenticate', () => {
        const counts = tokenCounts(
            {
                items: [
                    token('a'),
                    token('b'),
                    token('c', { username: 'grace' }),
                    token('d', { username: 'grace', revoked_at: '2026-02-01T00:00:00Z' }),
                ],
                next: null,
            },
            NOW,
        )
        expect(counts?.get('ada')).toBe(2)
        expect(counts?.get('grace')).toBe(1)
    })

    // REVERT-PROOF. A number off part of the listing would be too low and look right.
    test('says nothing where the read did not reach the end', () => {
        expect(tokenCounts({ items: [token('a')], next: 'more' }, NOW)).toBeNull()
    })
})
