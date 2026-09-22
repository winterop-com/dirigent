import { describe, expect, test } from 'vitest'

import { kindGlyph, NEUTRAL_GLYPH } from '@/lib/glyphs'

/** Every kind this repository contributes a connection kind or a notifier for. */
const SHIPPED = [
    'docker',
    'duckdb',
    'email',
    'git',
    'http',
    'kafka',
    'log',
    'rabbitmq',
    's3',
    'slack',
    'sql',
    'webhook',
]

describe('kindGlyph', () => {
    test('every kind this bundle ships is drawn by a mark of its own', () => {
        for (const kind of SHIPPED) {
            expect(kindGlyph(kind), kind).not.toBe(NEUTRAL_GLYPH)
        }
    })

    test('the notifiers are told apart from one another', () => {
        const notifiers = ['email', 'log', 'slack', 'webhook']
        expect(new Set(notifiers.map(kindGlyph)).size).toBe(notifiers.length)
    })

    test('the two queues wear the queue, and nothing else wears it', () => {
        expect(kindGlyph('kafka')).toBe(kindGlyph('rabbitmq'))
        expect(kindGlyph('http')).not.toBe(kindGlyph('kafka'))
    })

    test('a sql engine is drawn as the databases it opens', () => {
        expect(kindGlyph('duckdb')).toBe(kindGlyph('sql'))
    })

    test("a pack's kind this bundle cannot name takes the neutral glyph", () => {
        expect(kindGlyph('dhis2')).toBe(NEUTRAL_GLYPH)
        expect(kindGlyph('teams')).toBe(NEUTRAL_GLYPH)
        expect(kindGlyph('')).toBe(NEUTRAL_GLYPH)
    })

    test('a code that names a member of Object.prototype is not a glyph', () => {
        expect(kindGlyph('constructor')).toBe(NEUTRAL_GLYPH)
    })
})
