import { describe, expect, test } from 'vitest'

import { ICON_GROUPS, ICONS } from '@/lib/icons'

describe('the icon vocabulary', () => {
    test('draws no glyph for two concepts', () => {
        const seen = new Map<unknown, string>()
        for (const [concept, glyph] of Object.entries(ICONS)) {
            expect(
                seen.get(glyph),
                `${concept} reuses the glyph of ${String(seen.get(glyph))}`,
            ).toBeUndefined()
            seen.set(glyph, concept)
        }
    })

    test('puts every concept in exactly one group', () => {
        const grouped = Object.values(ICON_GROUPS).flat() as string[]
        expect(grouped.toSorted()).toEqual(Object.keys(ICONS).toSorted())
    })
})
