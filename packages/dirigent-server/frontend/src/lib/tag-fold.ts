/**
 * How many tag chips a row draws before the rest fold into one.
 *
 * A tag chip is mono at 12px, so how wide one is is arithmetic over its characters rather than a
 * question for the layout engine: every row folds against the one width its column declares.
 */

/** The advance of one character of the chip's face: IBM Plex Mono at 12px, 0.6em. */
export const CHIP_ADVANCE = 7.2

/** A chip's border and padding, either side of its word. */
export const CHIP_FRAME = 15

/** The gap between two chips. */
export const CHIP_GAP = 4

/** How many chips a row draws at most, however much room there is. */
export const TAGS_SHOWN = 8

/** How wide a chip carrying this word is drawn. */
export function chipWidth(word: string): number {
    return Math.ceil(word.length * CHIP_ADVANCE) + CHIP_FRAME
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
