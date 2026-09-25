/**
 * How wide a column in a listing is, and which of them gets the room first.
 *
 * A COLUMN HOLDS A VALUE OR IT HOLDS TEXT. A value -- a chip, an instant, a duration, a count --
 * is drawn from a fixed vocabulary and declares the floor it needs in its own classes. Text is
 * whatever somebody typed, declares no width at all, and takes what the value columns left.
 *
 * A TITLE IS NOT A DESCRIPTION. A title is short, it identifies the row, and a reader who cannot
 * read the whole of it cannot tell one row from another; a description is long, it is there to be
 * skimmed, and it is written to be cut. So a title column asks for the width its longest title
 * needs -- no more -- and the columns of prose beside it share what is left and truncate in it.
 * Where a title has no prose beside it there is nobody to give the rest to, and it takes the room
 * the way any other column of text does.
 *
 * THE TEXT COLUMNS ASK FOR THE WHOLE TABLE BETWEEN THEM. A column of text that asks for all of
 * it, as `w-full` does, is asking for more than there is, and a browser answers that by scaling
 * every such ask down together -- which hands a title a fraction of what it asked for and the
 * sentence beside it the rest. Asked for in shares that add up, with the value columns' measured
 * widths taken off first, each column is given exactly what it asked for.
 *
 * THE ASK IS A WIDTH, NEVER A FLOOR. A floor is what a listing measures itself against before it
 * gives up on drawing a table at all, so a title that declared the width it wants would turn the
 * narrow listings into cards. A share yields: where the floors under the columns beside it take
 * more than the table has left, the browser gives the title what remains, and the floor under
 * every column of text is the one it always had.
 */

/** What a column holds, which is what decides how wide it is. */
export type ColumnKind = 'value' | 'title' | 'prose'

/**
 * What a column of text carries.
 *
 * `max-w-0` is what lets it shrink and its content truncate; `w-full` is what it asks with until
 * the listing has measured itself and can say what each column's share is. The floor is 144px,
 * the width below which what it holds is an ellipsis rather than a fact.
 */
const TEXT_CLASS = 'w-full max-w-0 min-w-36'

/**
 * What a title column carries while it asks for a share of its own.
 *
 * No `w-full`: the layout that measures what the title needs is one the column stands at its
 * floor in, where the whole of the title runs past the cell and can be read off it. A column
 * already given the room it asked for runs past nothing and would measure as the room it has.
 */
const CLAIMING_CLASS = 'max-w-0 min-w-36'

/** The attributes a text cell is marked with, so the listing can measure its column. */
export const TITLE_CELL = 'data-list-title'
export const PROSE_CELL = 'data-list-prose'

/** How a column is sized: the classes its cells carry, and which share it is given. */
export interface Sizing {
    className: string
    /** The attribute this column's cells are marked with, or null where it is a value. */
    marks: typeof TITLE_CELL | typeof PROSE_CELL | null
}

const VALUE: Sizing = { className: '', marks: null }
const PROSE: Sizing = { className: TEXT_CLASS, marks: PROSE_CELL }
const TITLE: Sizing = { className: CLAIMING_CLASS, marks: TITLE_CELL }

/**
 * How one column is sized, from what it holds and what the columns beside it hold.
 *
 * The decision is the listing's rather than the screen's: a screen says what each column holds,
 * and two listings that put a title beside a description lay out the same way.
 */
export function sizingOf(kind: ColumnKind, kinds: readonly ColumnKind[]): Sizing {
    if (kind === 'value') return VALUE
    if (kind === 'prose') return PROSE
    return kinds.includes('prose') ? TITLE : PROSE
}

/** What the text columns ask for, as CSS widths. */
export interface Shares {
    /** What the title column asks for. */
    title: string
    /** What each column of prose beside it asks for. */
    prose: string
}

/** A width as a share of the listing, to two decimals, so rounding costs nobody a character. */
function share(width: number, room: number): string {
    return `${((width / room) * 100).toFixed(2)}%`
}

/**
 * What each column of text asks for: the title its own width, the prose an equal cut of the rest.
 *
 * `need` is what the longest title takes to read whole, `values` is what the columns that are not
 * text measured, `prose` is how many columns of prose stand beside the title, and `room` is the
 * listing's own width. Nothing measured yet is nothing to ask for, and the shares are the
 * listing's until its rows or its face change.
 *
 * A title with no prose beside it asks for everything, because there is nobody to hand the rest
 * to; a title that wants more than the table has asks for the table, and the floors under the
 * columns beside it are what actually decide how much of it it gets.
 */
export function sharesOf(need: number, values: number, prose: number, room: number): Shares | null {
    if (need <= 0 || room <= 0) return null
    if (prose === 0) return { title: '100%', prose: '100%' }
    const asked = Math.min(need, room)
    const left = Math.max(0, room - values - asked)
    return { title: share(asked, room), prose: share(left / prose, room) }
}
