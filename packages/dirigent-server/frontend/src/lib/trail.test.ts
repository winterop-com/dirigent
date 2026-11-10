import { beforeEach, describe, expect, test } from 'vitest'

import { clearScreenTrail, sameTrail, screenTrail, setScreenTrail } from '@/lib/trail'

beforeEach(() => {
    clearScreenTrail()
})

describe('the screen trail', () => {
    test('a trail saying the same steps is the trail already drawn', () => {
        const first = [{ label: 'Runs', href: '/runs' }]
        setScreenTrail(first)
        setScreenTrail([{ label: 'Runs', href: '/runs' }])
        expect(screenTrail.get()).toBe(first)
    })

    test('a step to another place, or in the code face, is a different trail', () => {
        expect(sameTrail([{ label: 'a', href: '/a' }], [{ label: 'a', href: '/b' }])).toBe(false)
        expect(sameTrail([{ label: 'a', href: '/a' }], [{ label: 'a', href: '/a', code: true }])).toBe(false)
        expect(sameTrail([], [{ label: 'a', href: '/a' }])).toBe(false)
    })

    test('clearing it states no trail', () => {
        setScreenTrail([{ label: 'Runs', href: '/runs' }])
        clearScreenTrail()
        expect(screenTrail.get()).toEqual([])
    })
})
