import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

import { settingsRows } from '@/lib/settings'
import {
    APPEARANCE_DEFAULTS,
    APPEARANCE_OFFER,
    DEFAULT_PALETTE,
    PALETTE_NAMES,
    PALETTES,
    MODE_ICONS,
    MODE_LABELS,
    MODES,
    modeOf,
} from '@/lib/theme'

const INDEX_HTML = fileURLToPath(new URL('../../index.html', import.meta.url))
const INDEX_CSS = fileURLToPath(new URL('../index.css', import.meta.url))

/** The library's file for one theme, as the package's exports map resolves it. */
function themeFile(name: string): string {
    return createRequire(import.meta.url).resolve(`@winterop-com/sokkel-ui/themes/${name}.css`)
}

/** The `<script>` tags in index.html, in document order. */
function scriptTags(html: string): string[] {
    return [...html.matchAll(/<script\b[^>]*>/g)].map((match) => match[0])
}

describe('the pre-paint script', () => {
    // With nothing stored, the script paints the palette in its own `data-theme` and the app then
    // wears `APPEARANCE_DEFAULTS`; two different answers flash one palette into the other.
    test('starts in the palette the app starts in', () => {
        const tag = scriptTags(readFileSync(INDEX_HTML, 'utf8')).find((one) => one.includes('/appearance.js'))
        expect(tag).toBeDefined()
        expect(/data-theme="([^"]*)"/.exec(tag ?? '')?.[1]).toBe(DEFAULT_PALETTE)
        expect(APPEARANCE_DEFAULTS.theme).toBe(DEFAULT_PALETTE)
    })

    // A stored theme outside the offered ones gives way before the first paint only if the script
    // offers the same themes the app does.
    test('offers the palettes the app offers', () => {
        const tag = scriptTags(readFileSync(INDEX_HTML, 'utf8')).find((one) => one.includes('/appearance.js'))
        expect(/data-themes="([^"]*)"/.exec(tag ?? '')?.[1].split(' ')).toEqual(PALETTE_NAMES)
        expect(APPEARANCE_OFFER.themes).toEqual(PALETTE_NAMES)
    })

    test('is the first script the document loads, and a classic one', () => {
        const [first] = scriptTags(readFileSync(INDEX_HTML, 'utf8'))
        expect(first).toContain('src="/appearance.js"')
        for (const attribute of ['type=', 'async', 'defer']) expect(first).not.toContain(attribute)
    })
})

describe('the palette axis', () => {
    // The order is the setting's order on screen, quiet to loud, and the cards render the array
    // as it stands.
    test('lists them quiet to loud, each with a label', () => {
        expect(PALETTE_NAMES).toEqual(['amber', 'paper', 'contrast'])
        for (const palette of PALETTES) expect(palette.label.length).toBeGreaterThan(0)
    })

    // A palette paints only once its theme file is imported, and its card on the Theme pane paints
    // its sample by scoping itself with `data-theme-scope`, which that file hangs the theme off as
    // well as off `data-theme`, in both modes.
    test('index.css imports every palette, and each scopes itself to a card', () => {
        const css = readFileSync(INDEX_CSS, 'utf8')
        for (const name of PALETTE_NAMES) {
            expect(css).toContain(`@import '@winterop-com/sokkel-ui/themes/${name}.css';`)
            const theme = readFileSync(themeFile(name), 'utf8')
            expect(theme).toContain(`[data-theme-scope='${name}'] {`)
            expect(theme).toContain(`.dark [data-theme-scope='${name}'] {`)
        }
    })

    test('the settings dialog offers the choice, in the theme category', () => {
        const rows = settingsRows(false).filter((row) => row.category === 'theme')
        expect(rows.map((row) => row.id)).toEqual(['theme:appearance', 'theme:palette'])
    })
})

describe('the mode axis', () => {
    test('reads each stored setting as itself', () => {
        for (const mode of MODES) expect(modeOf(mode)).toBe(mode)
    })

    test('reads nothing stored, or a value it does not know, as System', () => {
        expect(modeOf(undefined)).toBe('system')
        expect(modeOf('sepia')).toBe('system')
    })

    test('names and marks every setting, each with its own mark', () => {
        expect(Object.keys(MODE_LABELS).toSorted()).toEqual([...MODES].toSorted())
        expect(new Set(MODES.map((mode) => MODE_ICONS[mode])).size).toBe(MODES.length)
    })
})
