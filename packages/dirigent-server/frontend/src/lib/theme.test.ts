import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

import { rowsOf, settingsRows } from '@/lib/settings'
import {
    DEFAULT_PALETTE,
    PALETTE_NAMES,
    PALETTE_STORAGE_KEY,
    PALETTES,
    isPaletteName,
    paletteAfter,
} from '@/lib/theme'

const INDEX_HTML = fileURLToPath(new URL('../../index.html', import.meta.url))
const INDEX_CSS = fileURLToPath(new URL('../index.css', import.meta.url))

/** The palette names the pre-paint script in index.html knows about. */
function namesInIndexHtml(html: string): string[] {
    const list = /var known = \[([^\]]*)\]/.exec(html)
    if (list === null) throw new Error('index.html no longer declares a palette list')
    return [...list[1].matchAll(/'([^']+)'/g)].map((match) => match[1])
}

describe('the palette axis', () => {
    test('the pre-paint script knows exactly the palettes this module has', () => {
        const html = readFileSync(INDEX_HTML, 'utf8')
        expect(namesInIndexHtml(html)).toEqual(PALETTE_NAMES)
    })

    test('the pre-paint script reads the key this module writes', () => {
        expect(readFileSync(INDEX_HTML, 'utf8')).toContain(`localStorage.getItem('${PALETTE_STORAGE_KEY}')`)
    })

    test('a name this build does not have is read as the default rather than refused', () => {
        expect(isPaletteName('terminal')).toBe(false)
        expect(isPaletteName(null)).toBe(false)
        expect(PALETTE_NAMES).toContain(DEFAULT_PALETTE)
    })

    test('knows the three palettes this build ships, and nothing else', () => {
        for (const name of ['dirigent', 'paper', 'contrast']) expect(isPaletteName(name)).toBe(true)
        for (const name of ['light', 'dark', 'Paper', 'high-contrast', ''])
            expect(isPaletteName(name)).toBe(false)
    })

    // The order is the setting's order on screen, quiet to loud, and the swatches render the
    // array as it stands.
    test('lists them quiet to loud, each with a label', () => {
        expect(PALETTE_NAMES).toEqual(['dirigent', 'paper', 'contrast'])
        for (const palette of PALETTES) expect(palette.label.length).toBeGreaterThan(0)
    })

    // A swatch card paints its strips from the tokens of the palette it stands for, by scoping
    // itself with `data-palette`. That only works while index.css hangs every palette off that
    // attribute as well as off `data-theme`, both halves, the base palette included.
    test('index.css scopes every palette to a swatch as well as to the document', () => {
        const css = readFileSync(INDEX_CSS, 'utf8')
        for (const name of PALETTE_NAMES) {
            expect(css).toContain(`[data-palette='${name}'] {`)
            expect(css).toContain(`.dark [data-palette='${name}'] {`)
        }
    })

    test('the settings dialog offers the choice, in the theme category', () => {
        const rows = rowsOf(settingsRows(false), 'theme')
        expect(rows.map((row) => row.id)).toEqual(['theme:appearance', 'theme:palette'])
    })
})

describe('the arrows over the swatch cards', () => {
    test('move forward and back through the palettes in the order they are listed', () => {
        expect(paletteAfter('dirigent', 'ArrowRight')).toBe('paper')
        expect(paletteAfter('paper', 'ArrowDown')).toBe('contrast')
        expect(paletteAfter('contrast', 'ArrowLeft')).toBe('paper')
        expect(paletteAfter('paper', 'ArrowUp')).toBe('dirigent')
    })

    test('wrap at both ends, because a radio group is a ring', () => {
        expect(paletteAfter('contrast', 'ArrowRight')).toBe('dirigent')
        expect(paletteAfter('dirigent', 'ArrowLeft')).toBe('contrast')
    })

    // Space and Enter choose what already has focus, and every other key is the browser's.
    test('answer nothing to a key this control does not move on', () => {
        for (const key of [' ', 'Enter', 'Tab', 'Escape', 'a']) {
            expect(paletteAfter('dirigent', key)).toBeNull()
        }
    })
})
