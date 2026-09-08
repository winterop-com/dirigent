/**
 * How this app is painted.
 *
 * TWO INDEPENDENT AXES, AND KEEPING THEM APART IS THE WHOLE ARRANGEMENT. The **mode** is light
 * or dark: next-themes owns it, writes it as a `dark` class on `<html>`, and follows the
 * operating system until somebody says otherwise. The **palette** is which set of colours the
 * app spends inside that mode: this module owns it, writes it as `data-theme` on the same
 * element, and every palette is designed for both modes. Neither axis knows about the other.
 *
 * WHERE THE COLOURS ARE. Nowhere near here. A palette is a block of custom-property overrides
 * in index.css hung off `html[data-theme='<name>']`, beside the base one. This module carries
 * the names and nothing else, so adding a palette is a block of CSS plus one row in `PALETTES`.
 * The same blocks answer to `[data-palette='<name>']`, which is what lets the swatch card on the
 * Theme pane paint one palette's tokens while the app is wearing another.
 *
 * APPLIED BEFORE FIRST PAINT, by the inline script in index.html rather than here. A palette
 * read in a React effect arrives one frame after the document does, and every load flashes the
 * default under whatever was actually chosen. That script reads the same storage key this
 * module writes, so the store below starts on the palette the document is already painted in.
 */

import { createStore } from '@/lib/store'

/** The name a palette is stored and written under: its `data-theme` value. */
export type PaletteName = 'dirigent' | 'paper' | 'contrast'

/** One palette: what it is called on screen. What it looks like is the swatch, not a sentence. */
export interface Palette {
    name: PaletteName
    label: string
}

/** The palettes this build has, ordered quiet to loud. */
export const PALETTES: Palette[] = [
    { name: 'dirigent', label: 'Dirigent' },
    { name: 'paper', label: 'Paper' },
    { name: 'contrast', label: 'Contrast' },
]

export const DEFAULT_PALETTE: PaletteName = 'dirigent'

/** Where the chosen palette is kept, and the key the inline script in index.html reads. */
export const PALETTE_STORAGE_KEY = 'dirigent.palette'

/** The attribute on `<html>` the CSS blocks hang off. */
export const PALETTE_ATTRIBUTE = 'data-theme'

export const PALETTE_NAMES: PaletteName[] = PALETTES.map((palette) => palette.name)

/** Whether a string names a palette this build has. */
export function isPaletteName(candidate: string | null): candidate is PaletteName {
    return candidate !== null && (PALETTE_NAMES as string[]).includes(candidate)
}

/**
 * The palette this browser last chose, or the default.
 *
 * Storage that refuses to be read -- a private window, a browser with it denied -- is the same
 * answer as storage that holds nothing: the app is painted in the default and the choice simply
 * does not survive the reload.
 */
export function storedPalette(): PaletteName {
    try {
        const stored = localStorage.getItem(PALETTE_STORAGE_KEY)
        return isPaletteName(stored) ? stored : DEFAULT_PALETTE
    } catch {
        return DEFAULT_PALETTE
    }
}

/**
 * Which palette is painted, for the one control that offers the choice.
 *
 * The document is already wearing it before this module is fetched, so this starts where the
 * pre-paint script left off rather than deciding anything.
 */
export const paletteStore = createStore<PaletteName>(storedPalette())

/** Choose one palette: persist it, write it onto the document, and tell whoever is watching. */
export function choosePalette(name: string): PaletteName {
    const chosen = isPaletteName(name) ? name : DEFAULT_PALETTE
    try {
        localStorage.setItem(PALETTE_STORAGE_KEY, chosen)
    } catch {
        // Storage denied: the palette holds for as long as this document is open, and only
        // surviving the reload is lost.
    }
    document.documentElement.setAttribute(PALETTE_ATTRIBUTE, chosen)
    paletteStore.set(chosen)
    return chosen
}

/**
 * Which palette an arrow key moves to, or null for a key this control does not answer.
 *
 * The swatch cards are a radio group, so the arrows move and choose in one gesture and the ends
 * wrap. What the keys decide is a pure function; focusing the card that won is the component's.
 */
export function paletteAfter(current: PaletteName, key: string): PaletteName | null {
    const forward = key === 'ArrowRight' || key === 'ArrowDown'
    const back = key === 'ArrowLeft' || key === 'ArrowUp'
    if (!forward && !back) return null
    const at = PALETTE_NAMES.indexOf(current)
    const next = (at + (forward ? 1 : -1) + PALETTE_NAMES.length) % PALETTE_NAMES.length
    return PALETTE_NAMES[next]
}
