import { describe, expect, test } from 'vitest'

import { nextForm, SLACK, TABLE, type Form } from '@/lib/card-form'

/** A listing that turned into cards when the table in it took this much. */
function cards(natural: number): Form {
    return { cards: true, natural }
}

describe('which form a listing takes', () => {
    test('a table that fits its box stays a table', () => {
        expect(nextForm(TABLE, 712, 712)).toBe(TABLE)
    })

    test('a table wider than its box turns the listing into cards', () => {
        expect(nextForm(TABLE, 712, 761)).toEqual({ cards: true, natural: 761 })
    })

    test('what the table took is the threshold, not a pixel count written down', () => {
        const narrow = nextForm(TABLE, 346, 500)
        const wide = nextForm(TABLE, 346, 900)
        expect(narrow).toEqual({ cards: true, natural: 500 })
        expect(wide).toEqual({ cards: true, natural: 900 })
    })

    test('a listing in cards draws a table again once it has the width and the slack', () => {
        expect(nextForm(cards(761), 761 + SLACK, 0)).toBe(TABLE)
    })

    test('the width the table overflowed at is not enough to bring it back', () => {
        const form = cards(761)
        expect(nextForm(form, 761, 0)).toBe(form)
        expect(nextForm(form, 761 + SLACK - 1, 0)).toBe(form)
    })

    test('the two edges are apart, so a box dragged between them settles', () => {
        // Out at the width the table did not fit in, back only past that width and the slack:
        // a listing sat anywhere between the two keeps the form it has.
        const out = nextForm(TABLE, 760, 761)
        expect(out.cards).toBe(true)
        const back = nextForm(out, 761 + SLACK, 0)
        expect(back.cards).toBe(false)
        expect(nextForm(back, 761 + SLACK, 761)).toBe(back)
    })

    test('a box nothing has laid out yet settles nothing', () => {
        expect(nextForm(TABLE, 0, 0)).toBe(TABLE)
        const form = cards(761)
        expect(nextForm(form, 0, 0)).toBe(form)
    })

    test('a form that did not change is the same form, so nothing re-renders on it', () => {
        const form = cards(761)
        expect(nextForm(form, 400, 400)).toBe(form)
        expect(nextForm(TABLE, 1280, 900)).toBe(TABLE)
    })
})
