import { useCallback, useEffect, useLayoutEffect, useState } from 'react'

import { nextForm, TABLE, type Form } from '@/lib/card-form'
import { PROSE_CELL, sharesOf, TITLE_CELL, type Shares } from '@/lib/column-width'

/** What a listing's own box measured: the room it has, the form it allows, and its columns. */
export interface ListMeasure {
    /** How wide the listing is, which is what a cell deciding what fits works against. */
    width: number
    /** Whether the rows are drawn as cards rather than as a table. */
    cards: boolean
    /** What each column of text asks for, or null while the columns are unmeasured. */
    shares: Shares | null
}

/** What one row's columns measured while none of them had asked for anything. */
interface Columns {
    /** What the longest title takes to read whole, in fractions of a pixel. */
    need: number
    /** What the columns that are not text take between them, in fractions of a pixel. */
    values: number
    /** How many columns of prose stand beside the title. */
    prose: number
}

const NOTHING: Columns = { need: 0, values: 0, prose: 0 }

/** What a listing answers where there is no layout to measure, which is a table. */
const UNMEASURED: { width: number; form: Form; columns: Columns } = {
    width: 0,
    form: TABLE,
    columns: NOTHING,
}

/** The least a spill can be: under a thousandth of a pixel is arithmetic, not layout. */
const SPILL = 0.001

/** The right edge of the box this element gives its content, inside its padding and its border. */
function inside(element: Element): number {
    const style = globalThis.getComputedStyle(element)
    const edge = Number.parseFloat(style.paddingRight) + Number.parseFloat(style.borderRightWidth)
    return element.getBoundingClientRect().right - edge
}

/** The right edge of a text node, which is where its text reaches whatever clips it. */
function reach(text: Text): number {
    const range = globalThis.document.createRange()
    range.selectNode(text)
    let right = Number.NEGATIVE_INFINITY
    for (const rect of range.getClientRects()) right = Math.max(right, rect.right)
    return right
}

/**
 * How far what this element holds -- its child boxes, and the text it holds itself -- runs past
 * the box it was given.
 *
 * A child that clips its own content reaches no further than its own box, which is what stops
 * one overflow from being counted at every level above it; what that child is missing is the
 * deepest path's to report.
 */
function spill(element: Element): number {
    const room = inside(element)
    let held = room
    for (const part of element.childNodes) {
        if (part instanceof Element) held = Math.max(held, part.getBoundingClientRect().right)
        else if (part instanceof Text) held = Math.max(held, reach(part))
    }
    return held - room
}

/**
 * How far one cell's content runs past the room it was given, in fractions of a pixel.
 *
 * Summed down the deepest path rather than taken at one level: a title cut short inside a row
 * that itself overflowed -- a long code beside it holding its own width -- is short by both.
 *
 * READ IN FRACTIONS, NOT IN WHOLE PIXELS. `scrollWidth` and `clientWidth` answer in whole ones,
 * so a cell short of its content by a fraction of a pixel reads there as a cell with room to
 * spare -- while the browser, which lays out in fractions of one, has already drawn the ellipsis
 * and eaten the word in front of it. Every edge here is read off a client rect, which answers in
 * the fractions the layout was done in.
 */
function past(element: Element): number {
    let deepest = 0
    for (const part of element.children) deepest = Math.max(deepest, past(part))
    return Math.max(0, spill(element)) + deepest
}

/**
 * What this listing's columns are worth: the title's need, and what the value columns take.
 *
 * A CELL SAYS WHAT IT NEEDS ONLY WHEN IT IS SHORT OF IT. What it runs past its own room by is
 * the width it is missing, and a cell with room to spare says nothing at all -- so a column
 * given what it asked for measures the same again, and one whose rows grew under it, as a
 * listing's titles do when the names they were waiting for land, measures the difference and
 * asks again. The first measurement is the one the title stands at its floor for, and it is
 * the only one a title short enough to fit its floor is read on.
 */
function columnsOf(box: HTMLElement, held: Columns): Columns {
    let need = held.need
    for (const cell of box.querySelectorAll<HTMLElement>(`[${TITLE_CELL}]`)) {
        const over = past(cell)
        const width = cell.getBoundingClientRect().width
        // A cell that runs past its room needs that much more; one that does not, on the layout
        // it stands at its floor in, needs no more than the floor.
        if (over > SPILL) need = Math.max(need, width + over)
        else if (held.need === 0) need = Math.max(need, width)
    }
    if (need === 0) return NOTHING
    // WHAT THE VALUE COLUMNS TAKE IS READ ONCE. They are shrink-to-content, so what they measure
    // on the layout before any share was asked for is what they are worth; reading them again
    // under the shares computed from them is a measurement that answers its own question.
    if (held.need > 0) return { ...held, need }
    let values = 0
    let prose = 0
    for (const cell of box.querySelector('tbody tr')?.children ?? []) {
        if (cell.hasAttribute(PROSE_CELL)) prose += 1
        else if (!cell.hasAttribute(TITLE_CELL)) values += cell.getBoundingClientRect().width
    }
    return { need, values, prose }
}

/** Whether two measurements of a listing's columns say the same thing. */
function same(one: Columns, other: Columns): boolean {
    return one.need === other.need && one.values === other.values && one.prose === other.prose
}

/**
 * How much room a listing has, and whether the table drawn in it fits.
 *
 * ONE OBSERVER, NOT ONE PER ROW. Both answers come off the listing's own card -- the room from
 * `clientWidth`, what the columns take from `scrollWidth` -- so a cell that has to decide what
 * fits reads the number this measured rather than measuring itself, which would be a read per
 * row on every resize.
 *
 * MEASURED BEFORE IT IS SEEN. The rows that just arrived are what the table's width is made of,
 * and a box does not resize when its content grows, so the measurement is a layout effect after
 * every render rather than the observer's alone: a listing that cannot hold its table has turned
 * into cards before the frame it would have overflowed in is painted. `nextForm` answers with
 * the form it was given where nothing changed, so a render that settles nothing renders nothing.
 */
export function useCardForm(box: HTMLElement | null, shown: string): ListMeasure {
    const [measured, setMeasured] = useState(UNMEASURED)

    const measure = useCallback(() => {
        if (box === null) return
        const room = box.clientWidth
        const taken = box.scrollWidth
        // The layout is the external thing this synchronizes with, and it cannot be read until
        // the DOM has been written: the form is settled before the frame is painted rather than
        // in the frame after it.
        // oxlint-disable-next-line react/set-state-in-effect
        setMeasured((held) => {
            // A WIDTH IS PUBLISHED BEFORE IT IS JUDGED. A cell that fits itself to the listing
            // reads a width nothing has measured yet as no bound at all and draws everything it
            // holds, so a layout made before this listing knew its own width is not the layout
            // to settle the form on. The render that follows this one is.
            if (room !== held.width) return { ...held, width: room }
            // THE COLUMNS SETTLE BEFORE THE FORM DOES. The layout the columns are first measured
            // on is one the title stands at its floor in, and a table narrower than the one that
            // will be drawn says nothing about whether the real one fits.
            const columns = columnsOf(box, held.columns)
            if (!same(columns, held.columns)) return { ...held, columns }
            const form = nextForm(held.form, room, taken)
            return form === held.form ? held : { ...held, width: room, form }
        })
    }, [box])

    // What the columns are worth is the rows' and the face's, not the layout's, so it is
    // forgotten when either changes and read again on the layout that follows.
    const forget = useCallback(() => {
        // The rows and the face are the external things this synchronizes with, and neither is
        // knowable during a render: what is dropped here is read back by the layout effect that
        // follows, before anything is painted.
        // oxlint-disable-next-line react/set-state-in-effect
        setMeasured((held) => (held.columns.need === 0 ? held : { ...held, columns: NOTHING }))
    }, [])

    useEffect(forget, [forget, shown])

    useLayoutEffect(measure)

    useEffect(() => {
        if (box === null || typeof ResizeObserver === 'undefined') return
        const observer = new ResizeObserver(measure)
        observer.observe(box)
        return () => {
            observer.disconnect()
        }
    }, [box, measure])

    // A face that arrives after the first paint re-cuts every word in the table without
    // resizing anything the observer is watching, so the widths are read again behind it.
    useEffect(() => {
        void globalThis.document.fonts?.ready.then(forget)
    }, [forget])

    const columns = measured.columns
    return {
        width: measured.width,
        cards: measured.form.cards,
        shares: sharesOf(columns.need, columns.values, columns.prose, measured.width),
    }
}
