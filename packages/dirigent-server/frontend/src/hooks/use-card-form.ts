import { useCallback, useEffect, useLayoutEffect, useState } from 'react'

import { nextForm, TABLE, type Form } from '@/lib/card-form'

/** What a listing's own box measured: the room it has, and the form that room allows. */
export interface ListBox {
    /** How wide the listing is, which is what a cell deciding what fits works against. */
    width: number
    /** Whether the rows are drawn as cards rather than as a table. */
    cards: boolean
}

/** What a listing answers where there is no layout to measure, which is a table. */
const UNMEASURED: { width: number; form: Form } = { width: 0, form: TABLE }

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
export function useCardForm(box: HTMLElement | null): ListBox {
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
            if (room !== held.width) return { width: room, form: held.form }
            const form = nextForm(held.form, room, taken)
            return form === held.form ? held : { width: room, form }
        })
    }, [box])

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
        void globalThis.document.fonts?.ready.then(measure)
    }, [measure])

    return { width: measured.width, cards: measured.form.cards }
}
