/**
 * Whether a listing draws its rows as a table or as cards.
 *
 * THE LISTING'S OWN WIDTH DECIDES, NOT THE WINDOW'S. The same columns fit a phone-sized window
 * with nothing in front of them and overflow a 1024px one with a rail beside it, and overflow
 * again the moment a panel takes half of what was left -- so the question a media query answers
 * is not the question being asked. What is asked here is whether the box the listing is standing
 * in can hold the table drawn in it.
 *
 * THE THRESHOLD IS MEASURED, NOT WRITTEN DOWN. A table lays out at the width its columns need
 * whatever box it is in, so a table wider than its box is the listing saying it cannot hold one,
 * and that width is what it has to get back before it draws one again. A pixel count in this
 * file would be a guess about columns it cannot see.
 *
 * THE EDGE HAS SLACK IN IT. Returning to a table at exactly the width the table takes is
 * returning to it at the width it overflows at, so a window dragged across that edge would
 * strobe between the two forms.
 */

/**
 * How much more than the table's own width a listing needs before it draws one again.
 *
 * Wider than the 10px scrollbar the taller card form can bring in, which is the one thing that
 * changes a listing's room by changing its form.
 */
export const SLACK = 16

export interface Form {
    /** Whether the rows are drawn as cards. */
    cards: boolean
    /** What the table took the last time one overflowed this listing, and 0 while one fits. */
    natural: number
}

/** The form a listing starts in, and the one it returns to: a table, until one does not fit. */
export const TABLE: Form = { cards: false, natural: 0 }

/**
 * The form this listing takes next, from the room it has and what is drawn in it.
 *
 * `room` is the listing's own box -- `clientWidth` -- and `taken` is what stands in it, which
 * while a table is drawn is the table's width and is greater than the box exactly when the
 * columns do not fit. Both are integers off the layout, so a fraction of a pixel is not an
 * overflow.
 *
 * The form is returned unchanged, and identical, where nothing about it changed, so a caller
 * holding it as state re-renders only on a real answer.
 */
export function nextForm(now: Form, room: number, taken: number): Form {
    // A box nothing has laid out yet answers no question.
    if (room <= 0) return now
    if (now.cards) return room >= now.natural + SLACK ? TABLE : now
    return taken > room ? { cards: true, natural: taken } : now
}
