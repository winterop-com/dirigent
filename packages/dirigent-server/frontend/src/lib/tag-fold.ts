/**
 * How many tag chips a listing row draws before the rest fold into one.
 *
 * THE WIDTH IS MEASURED ONCE, THE CHIPS ARE COMPUTED. A tag chip is mono at 12px, so how wide
 * one is is arithmetic over its characters rather than a question for the layout engine: the
 * table is measured once by a `ResizeObserver` on the listing's own card, and every row folds
 * against that one number. Measuring each row's own cell instead would be a read per row per
 * resize, and a cell that is as wide as what is in it would answer with the width the chips
 * already took -- the question is what room the row's identity is prepared to give up, and
 * that is a share of the table.
 *
 * ONE LINE, EXCEPT ON A WIDE TABLE. A row whose height depends on how many words it wears makes
 * a listing of twenty rows a listing of twenty heights, so the chips fold to one line and only
 * a table at `WRAPS_AT` or wider is allowed a second.
 */

/** The advance of one character of the chip's face: IBM Plex Mono at 12px. */
export const CHIP_ADVANCE = 7.2

/** A chip's border and padding, either side of its word. */
export const CHIP_FRAME = 15

/** The gap between two chips. */
export const CHIP_GAP = 4

/** How many chips a row draws at most, however much room there is. */
export const TAGS_SHOWN = 8

/** The share of the table the chips may take. */
export const TAGS_SHARE = 0.25

/** The share of the table the identity keeps, whatever else is on the row. */
export const LEAD_SHARE = 0.5

/** The table width at which a second line of chips is allowed. */
export const WRAPS_AT = 1280

/** How wide a chip carrying this word is drawn. */
export function chipWidth(word: string): number {
    return Math.ceil(word.length * CHIP_ADVANCE) + CHIP_FRAME
}

/** How many lines of chips a table of this width allows. */
export function linesFor(table: number): number {
    return table >= WRAPS_AT ? 2 : 1
}

/** A table cell's own padding, either side of what is in it. */
export const CELL_PADDING = 24

/** The room the chips have on a table of this width, inside the cell's own padding. */
export function roomFor(table: number): number {
    return table * TAGS_SHARE - CELL_PADDING
}

/** What a row draws, and what it folds away. */
export interface Fold {
    shown: string[]
    folded: string[]
}

/**
 * Fit as many chips as the room holds, and fold the rest behind one that says how many.
 *
 * The fold is a chip too, so it has to fit in the room it is being made for: a `+N` drawn past
 * the edge is the wrapping this is here to prevent. A room too small for even one chip still
 * draws one, because a cell holding nothing but `+15` says nothing about the row.
 */
export function foldTags(tags: readonly string[], room: number, lines: number): Fold {
    const capped = tags.slice(0, TAGS_SHOWN)
    if (room <= 0) return { shown: [...capped], folded: tags.slice(capped.length) }
    if (fits(capped, room, lines) && capped.length === tags.length) {
        return { shown: [...capped], folded: [] }
    }
    for (let count = capped.length; count > 1; count -= 1) {
        const shown = capped.slice(0, count)
        const folded = tags.slice(count)
        if (fits([...shown, `+${String(folded.length)}`], room, lines)) return { shown, folded }
    }
    return { shown: capped.slice(0, 1), folded: tags.slice(1) }
}

/** Whether these chips are drawn on this many lines of this width. */
function fits(words: readonly string[], room: number, lines: number): boolean {
    let used = 0
    let line = 1
    for (const word of words) {
        const width = chipWidth(word)
        const next = used === 0 ? width : used + CHIP_GAP + width
        if (next <= room) {
            used = next
            continue
        }
        line += 1
        used = width
        if (line > lines || width > room) return false
    }
    return true
}
