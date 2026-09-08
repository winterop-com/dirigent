/**
 * How wide the login's brand pane is, when a reader has said.
 *
 * The pane's own rule is a clamp and stays one until somebody drags the seam; from then on this
 * browser holds a number of pixels, the way every other dragged edge in this app does. It is a
 * per-viewer convenience: storage that refuses to be read or written is the same answer as
 * storage that holds nothing, and the clamp comes back.
 */

/** Where the chosen width is kept. */
export const PANE_STORAGE_KEY = 'dirigent.login.pane'

/** The narrowest the pane may be, which is the floor its own clamp already has. */
export const PANE_MIN = 560

/** The widest, which is the ceiling its own clamp already has. */
export const PANE_MAX = 1056

/**
 * What the form column cannot go without: the form's own width and the padding either side of
 * it. A pane dragged past this would take room the question needs.
 */
export const FORM_COLUMN = 526

/** How far one press of an arrow key moves the seam, and how far a shifted one does. */
export const PANE_STEP = 16
export const PANE_BIG_STEP = 64

/** The bounds the seam moves between in a window of this width. */
export function paneBounds(windowWidth: number): { min: number; max: number } {
    return {
        min: PANE_MIN,
        max: Math.max(PANE_MIN, Math.min(PANE_MAX, windowWidth - FORM_COLUMN)),
    }
}

/**
 * A chosen width held inside those bounds.
 *
 * A window narrower than the two columns need is why this takes the width rather than reading
 * it: the pane keeps its floor and the form column gives up the difference, which is the same
 * answer a resize gets and a stored choice from a wider screen gets.
 */
export function clampPaneWidth(chosen: number, windowWidth: number): number {
    const { min, max } = paneBounds(windowWidth)
    return Math.min(Math.max(Math.round(chosen), min), max)
}

/** The width this browser last chose, or null where none was chosen. */
export function rememberedPaneWidth(): number | null {
    try {
        const stored = localStorage.getItem(PANE_STORAGE_KEY)
        if (stored === null) return null
        const width = Number(stored)
        return Number.isFinite(width) && width > 0 ? width : null
    } catch {
        return null
    }
}

/** Keep a chosen width for the next visit. Null forgets it, and the clamp rules again. */
export function rememberPaneWidth(width: number | null): void {
    try {
        if (width === null) localStorage.removeItem(PANE_STORAGE_KEY)
        else localStorage.setItem(PANE_STORAGE_KEY, String(Math.round(width)))
    } catch {
        // Storage denied: the seam still drags, and only the choice on the next visit is lost.
    }
}
