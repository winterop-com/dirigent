import { createElement, type ReactElement } from 'react'
import { describe, expect, test } from 'vitest'

import { kindGlyph, NEUTRAL_GLYPH, type Glyph, type KindMarks } from '@/lib/glyphs'

/** Every kind this repository contributes a connection kind or a notifier for. */
const SHIPPED = [
    'docker',
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
        expect(new Set(notifiers.map((kind) => kindGlyph(kind))).size).toBe(notifiers.length)
    })

    test('the two queues wear the queue, and nothing else wears it', () => {
        expect(kindGlyph('kafka')).toBe(kindGlyph('rabbitmq'))
        expect(kindGlyph('http')).not.toBe(kindGlyph('kafka'))
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

/** A plausible mark: a ring with a bar in it, of the sort a pack declares. */
const DECLARED = 'M2 12a10 10 0 1 0 20 0a10 10 0 1 0-20 0ZM10.5 7h3v10h-3Z'

/** The `d` a glyph draws, read off the element it builds rather than off a rendered DOM. */
function pathDrawn(glyph: Glyph): unknown {
    const drawn = (glyph as (props: object) => ReactElement<{ children: ReactElement<{ d: unknown }> }>)({})
    return drawn.props.children.props.d
}

describe('kindGlyph over the marks a catalog carries', () => {
    test("a pack's kind is drawn by the path the pack declared", () => {
        const marks: KindMarks = new Map([['dhis2', DECLARED]])
        const glyph = kindGlyph('dhis2', marks)
        expect(glyph).not.toBe(NEUTRAL_GLYPH)
        expect(pathDrawn(glyph)).toBe(DECLARED)
        expect(createElement(glyph)).toBeTruthy()
    })

    test('one declared mark is one glyph, so nothing drawing it remounts', () => {
        expect(kindGlyph('dhis2', new Map([['dhis2', DECLARED]]))).toBe(
            kindGlyph('dhis2', new Map([['dhis2', DECLARED]])),
        )
    })

    test('the built-in mark wins over one a pack declares for the same kind', () => {
        expect(kindGlyph('slack', new Map([['slack', DECLARED]]))).toBe(kindGlyph('slack'))
    })

    test('a kind with neither a built-in mark nor a declared one takes the neutral glyph', () => {
        expect(kindGlyph('dhis2', new Map([['other', DECLARED]]))).toBe(NEUTRAL_GLYPH)
        expect(kindGlyph('dhis2', new Map())).toBe(NEUTRAL_GLYPH)
    })

    test('a mark that is not path data is never drawn', () => {
        const refused = [
            '',
            '   ',
            '"/><script>alert(1)</script>',
            'url(#steal)',
            'M0 0 L1 1 é',
            `M0 0${'z'.repeat(4096)}`,
        ]
        for (const mark of refused) {
            expect(kindGlyph('dhis2', new Map([['dhis2', mark]])), mark).toBe(NEUTRAL_GLYPH)
        }
    })

    test('path data right up to the limit is drawn', () => {
        const long = `M0 0${'z'.repeat(4092)}`
        expect(long.length).toBe(4096)
        expect(kindGlyph('dhis2', new Map([['dhis2', long]]))).not.toBe(NEUTRAL_GLYPH)
    })
})
