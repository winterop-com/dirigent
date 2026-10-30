import { describe, expect, test } from 'vitest'

import { ICONS } from '@/lib/icons'

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
})
