/**
 * The look this app starts in, and which of sokkel-ui's themes it carries the styles of.
 *
 * sokkel-ui keeps and wears the look: `useAppearance` stores the theme, scheme, density, corners,
 * typeface and motion and writes them on `<html>`, and its `appearance.js`, which index.html loads
 * at the top of `<head>`, writes the stored look before the first paint. The themes, their names
 * and the words that offer them are the library's.
 *
 * `CARRIED_THEMES` are the themes whose files index.css imports, the only ones offered: a stored
 * theme outside them gives way to the default. The pre-paint script names the same default and the
 * same themes in its data attributes; a test holds them equal.
 */

import {
    THEMES,
    type AppearanceOffer,
    type ThemeOption,
    type ThemeSettings,
} from '@winterop-com/sokkel-ui/lib/appearance'

/** The library themes whose files index.css imports. */
export const CARRIED_THEMES: readonly string[] = ['amber', 'paper', 'contrast']

/** The look `useAppearance` starts in until somebody chooses otherwise. */
export const APPEARANCE_DEFAULTS: Partial<ThemeSettings> = { theme: 'amber', scheme: 'system' }

/** The themes `useAppearance` may wear. */
export const APPEARANCE_OFFER: AppearanceOffer = { themes: CARRIED_THEMES }

/** The library's own options for the carried themes, as Settings and the palette offer them. */
export const APPEARANCE_THEMES: readonly ThemeOption[] = THEMES.filter((theme) =>
    CARRIED_THEMES.includes(theme.value),
)
