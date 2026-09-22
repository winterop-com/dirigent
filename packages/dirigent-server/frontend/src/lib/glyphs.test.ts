import { describe, expect, test } from 'vitest'

import { channelGlyph, NEUTRAL_GLYPH } from '@/lib/glyphs'

describe('channelGlyph', () => {
    test('a channel this bundle names is drawn by its own mark', () => {
        for (const notifier of ['email', 'log', 'slack', 'webhook']) {
            expect(channelGlyph(notifier)).not.toBe(NEUTRAL_GLYPH)
        }
        expect(new Set(['email', 'log', 'slack', 'webhook'].map(channelGlyph)).size).toBe(4)
    })

    test('a notifier a pack contributed and this bundle cannot name takes the neutral glyph', () => {
        expect(channelGlyph('teams')).toBe(NEUTRAL_GLYPH)
        expect(channelGlyph('')).toBe(NEUTRAL_GLYPH)
    })

    test('a code that names a member of Object.prototype is not a glyph', () => {
        expect(channelGlyph('constructor')).toBe(NEUTRAL_GLYPH)
    })
})
