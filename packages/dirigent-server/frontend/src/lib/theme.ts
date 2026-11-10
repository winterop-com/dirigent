/**
 * What this app offers on its two theme axes, and what each choice is called.
 *
 * TWO INDEPENDENT AXES. The **mode** is light, dark or system, worn as a `dark` class on `<html>`.
 * The **palette** is which set of colors the app spends inside that mode, worn as `data-theme` on
 * the same element, and every palette is designed for both modes. Neither axis knows about the
 * other.
 *
 * SOKKEL-UI KEEPS BOTH. `useAppearance` stores the choice and writes it on `<html>`, and the
 * library's `appearance.js`, which index.html loads at the top of `<head>`, writes the stored
 * choice before the first paint. This module names what dirigent offers and stores nothing.
 *
 * A PALETTE IS ONE OF THE LIBRARY'S THEMES: a file of custom-property overrides hung off
 * `html[data-theme='<name>']`, imported in index.css, plus one row in `PALETTES`. The same blocks
 * answer to `[data-theme-scope='<name>']`, which is what lets the swatch card on the Theme pane
 * paint one palette's tokens while the app is wearing another.
 *
 * The pre-paint script takes its default from its own `data-theme` attribute in index.html, which
 * has to name `DEFAULT_PALETTE`; a test holds the two equal.
 */

import type { AppearanceOffer, ThemeSettings } from '@winterop-com/sokkel-ui/lib/appearance'

import { ICONS, type Icon } from '@/lib/icons'
import { LABELS } from '@/lib/labels'

/** The three settings of the mode axis, as sokkel-ui stores them. */
export const MODES = ['light', 'dark', 'system'] as const

export type Mode = (typeof MODES)[number]

/** What each setting is called: on the Theme pane, in the account menu, and in the palette. */
export const MODE_LABELS: Record<Mode, string> = {
    light: LABELS.shell.mode.light,
    dark: LABELS.shell.mode.dark,
    system: LABELS.shell.mode.system,
}

/** The mark each setting is drawn with. */
export const MODE_ICONS: Record<Mode, Icon> = {
    light: ICONS.light,
    dark: ICONS.dark,
    system: ICONS.system,
}

/** A setting read as one of the three; anything else is System. */
export function modeOf(theme: string | undefined): Mode {
    return MODES.find((mode) => mode === theme) ?? 'system'
}

/** The name a palette is stored and written under: its `data-theme` value. */
export type PaletteName = 'amber' | 'paper' | 'contrast'

/** One palette: what it is called on screen. What it looks like is the swatch, not a sentence. */
export interface Palette {
    name: PaletteName
    label: string
}

/** The palettes this build has, ordered quiet to loud. Only these have their theme file imported. */
export const PALETTES: Palette[] = [
    { name: 'amber', label: LABELS.shell.colours.amber },
    { name: 'paper', label: LABELS.shell.colours.paper },
    { name: 'contrast', label: LABELS.shell.colours.contrast },
]

export const DEFAULT_PALETTE: PaletteName = 'amber'

/** The look `useAppearance` starts in until somebody chooses otherwise. */
export const APPEARANCE_DEFAULTS: Partial<ThemeSettings> = { theme: DEFAULT_PALETTE }

export const PALETTE_NAMES: PaletteName[] = PALETTES.map((palette) => palette.name)

/** The themes `useAppearance` may wear; a stored one outside them gives way to the default. */
export const APPEARANCE_OFFER: AppearanceOffer = { themes: PALETTE_NAMES }

/** The palette a stored theme names; a theme this build does not offer reads as the default. */
export function paletteOf(theme: string): PaletteName {
    return PALETTE_NAMES.find((name) => name === theme) ?? DEFAULT_PALETTE
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
