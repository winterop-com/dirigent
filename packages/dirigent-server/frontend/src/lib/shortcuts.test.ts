import { describe, expect, test } from 'vitest'

import { applePlatform, shortcuts } from '@/lib/shortcuts'

describe('the list of shortcuts', () => {
    test('binds letters and nothing else, because a bracket needs Alt on a Nordic layout', () => {
        const bound = shortcuts(true).flatMap((row) => row.keys)
        expect(bound.filter((key) => /^[[\]{}|\\]$/.test(key))).toEqual([])
    })

    test('spells the modifier the way the platform spells it', () => {
        expect(shortcuts(true)[0].keys[0]).toBe('⌘')
        expect(shortcuts(false)[0].keys[0]).toBe('Ctrl')
    })
})

describe('the platform', () => {
    test('is read off the user agent, which is what decides how a chord is spelled', () => {
        expect(applePlatform('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')).toBe(true)
        expect(applePlatform('Mozilla/5.0 (X11; Linux x86_64)')).toBe(false)
    })
})
