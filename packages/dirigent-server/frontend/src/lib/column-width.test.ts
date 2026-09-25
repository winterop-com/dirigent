import { describe, expect, test } from 'vitest'

import { PROSE_CELL, sharesOf, sizingOf, TITLE_CELL, type ColumnKind } from '@/lib/column-width'

/** The columns of a listing that heads its rows with a title and describes them beside it. */
const DESCRIBED: ColumnKind[] = ['title', 'prose']

/** The columns of a listing whose title is the only text on the row. */
const ALONE: ColumnKind[] = ['title', 'value', 'value']

describe('how wide a column is', () => {
    test('a value column declares its own width and is given none', () => {
        expect(sizingOf('value', DESCRIBED)).toEqual({ className: '', marks: null })
    })

    test('a column of prose takes what the value columns left until it is given a share', () => {
        expect(sizingOf('prose', DESCRIBED).className).toContain('w-full')
        expect(sizingOf('prose', DESCRIBED).marks).toBe(PROSE_CELL)
    })

    test('a title beside a description stands at its floor until it is given a share', () => {
        const sizing = sizingOf('title', DESCRIBED)
        expect(sizing.marks).toBe(TITLE_CELL)
        expect(sizing.className).not.toContain('w-full')
    })

    test('a title with no description beside it keeps the room, like any other text', () => {
        expect(sizingOf('title', ALONE)).toEqual(sizingOf('prose', ALONE))
    })

    test('every column of text stands on the same floor, titles and prose alike', () => {
        expect(sizingOf('title', DESCRIBED).className).toContain('min-w-36')
        expect(sizingOf('prose', DESCRIBED).className).toContain('min-w-36')
    })
})

describe('what the columns of text ask for', () => {
    test('the title asks for what it needs and the prose for what is left', () => {
        expect(sharesOf(300, 0, 1, 600)).toEqual({ title: '50.00%', prose: '50.00%' })
    })

    test('the value columns are taken off before the rest is shared', () => {
        // 200 of the 600 belong to the chips and instants, 150 to the title: 250 are left.
        expect(sharesOf(150, 200, 1, 600)).toEqual({ title: '25.00%', prose: '41.66%' })
    })

    test('two columns of prose beside a title cut what is left in half each', () => {
        expect(sharesOf(200, 0, 2, 800)).toEqual({ title: '25.00%', prose: '37.50%' })
    })

    test('a title with no prose beside it asks for the whole table', () => {
        expect(sharesOf(200, 100, 0, 600)?.title).toBe('100%')
    })

    test('a title wanting more than the table asks for the table, and the floors decide', () => {
        expect(sharesOf(900, 0, 1, 600)).toEqual({ title: '100.00%', prose: '0.00%' })
    })

    test('nothing measured is nothing to ask for', () => {
        expect(sharesOf(0, 0, 1, 600)).toBeNull()
        expect(sharesOf(200, 0, 1, 0)).toBeNull()
    })

    test('the shares are of the listing, so the same title asks for less of a wider one', () => {
        expect(sharesOf(382, 0, 1, 604)?.title).toBe('63.25%')
        expect(sharesOf(382, 0, 1, 1240)?.title).toBe('30.81%')
    })

    test('a need measured in fractions of a pixel is asked for in whole ones', () => {
        // The schemas listing at 1280: 389.98px of title in a 988px table. Asked for as it was
        // measured the title is granted 389.96 and loses its last word; the whole pixel above
        // is the width no title in it is short of.
        expect(sharesOf(389.984_375, 0, 1, 988)?.title).toBe('39.48%')
    })

    test('a share never grants less than the need where the listing has room for it', () => {
        const room = 988
        for (const need of [144, 261.5, 389.984_375, 390, 390.5, 512.015_625]) {
            const granted = (pixels(sharesOf(need, 0, 1, room)?.title) / 100) * room
            expect(granted).toBeGreaterThanOrEqual(need)
        }
    })

    test('what the columns ask for between them is never more than the listing has', () => {
        for (const room of [712, 968, 988, 1240]) {
            for (const need of [200.4, 389.984_375, 512]) {
                const shares = sharesOf(need, 120.5, 2, room)
                const asked = pixels(shares?.title) + 2 * pixels(shares?.prose)
                expect(asked + (120.5 / room) * 100).toBeLessThanOrEqual(100)
            }
        }
    })
})

/** A share read back as the number it states, which is what the browser resolves it as. */
function pixels(share: string | undefined): number {
    return Number.parseFloat(share ?? '')
}
