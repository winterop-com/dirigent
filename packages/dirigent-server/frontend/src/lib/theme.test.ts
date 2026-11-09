import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

import { rowsOf, settingsRows } from '@/lib/settings'
import {
    DEFAULT_PALETTE,
    PALETTE_NAMES,
    PALETTE_STORAGE_KEY,
    PALETTES,
    isPaletteName,
    MODE_ICONS,
    MODE_LABELS,
    MODES,
    modeOf,
    paletteAfter,
} from '@/lib/theme'

const PALETTE_JS = fileURLToPath(new URL('../../public/palette.js', import.meta.url))
const INDEX_CSS = fileURLToPath(new URL('../index.css', import.meta.url))

/** The library's file for one theme, as the package's exports map resolves it. */
function themeFile(name: string): string {
    return createRequire(import.meta.url).resolve(`@winterop-com/sokkel-ui/themes/${name}.css`)
}

/** The palette names the pre-paint script knows about. */
function namesInPaletteScript(script: string): string[] {
    const list = /var known = \[([^\]]*)\]/.exec(script)
    if (list === null) throw new Error('palette.js no longer declares a palette list')
    return [...list[1].matchAll(/'([^']+)'/g)].map((match) => match[1])
}

describe('the palette axis', () => {
    test('the pre-paint script knows exactly the palettes this module has', () => {
        const script = readFileSync(PALETTE_JS, 'utf8')
        expect(namesInPaletteScript(script)).toEqual(PALETTE_NAMES)
    })

    test('the pre-paint script reads the key this module writes', () => {
        expect(readFileSync(PALETTE_JS, 'utf8')).toContain(`localStorage.getItem('${PALETTE_STORAGE_KEY}')`)
    })

    test('a name this build does not have is read as the default rather than refused', () => {
        expect(isPaletteName('terminal')).toBe(false)
        expect(isPaletteName(null)).toBe(false)
        expect(PALETTE_NAMES).toContain(DEFAULT_PALETTE)
    })

    test('knows the three palettes this build ships, and nothing else', () => {
        for (const name of ['amber', 'paper', 'contrast']) expect(isPaletteName(name)).toBe(true)
        for (const name of ['dirigent', 'light', 'dark', 'Paper', 'high-contrast', ''])
            expect(isPaletteName(name)).toBe(false)
    })

    // The order is the setting's order on screen, quiet to loud, and the swatches render the
    // array as it stands.
    test('lists them quiet to loud, each with a label', () => {
        expect(PALETTE_NAMES).toEqual(['amber', 'paper', 'contrast'])
        for (const palette of PALETTES) expect(palette.label.length).toBeGreaterThan(0)
    })

    // A palette paints only once its theme file is imported, and a swatch card paints its strips
    // by scoping itself with `data-theme-scope`, which that file hangs the theme off as well as
    // off `data-theme`, in both modes.
    test('index.css imports every palette, and each scopes itself to a swatch', () => {
        const css = readFileSync(INDEX_CSS, 'utf8')
        for (const name of PALETTE_NAMES) {
            expect(css).toContain(`@import '@winterop-com/sokkel-ui/themes/${name}.css';`)
            const theme = readFileSync(themeFile(name), 'utf8')
            expect(theme).toContain(`[data-theme-scope='${name}'] {`)
            expect(theme).toContain(`.dark [data-theme-scope='${name}'] {`)
        }
    })

    test('the settings dialog offers the choice, in the theme category', () => {
        const rows = rowsOf(settingsRows(false), 'theme')
        expect(rows.map((row) => row.id)).toEqual(['theme:appearance', 'theme:palette'])
    })
})

describe('the arrows over the swatch cards', () => {
    test('move forward and back through the palettes in the order they are listed', () => {
        expect(paletteAfter('amber', 'ArrowRight')).toBe('paper')
        expect(paletteAfter('paper', 'ArrowDown')).toBe('contrast')
        expect(paletteAfter('contrast', 'ArrowLeft')).toBe('paper')
        expect(paletteAfter('paper', 'ArrowUp')).toBe('amber')
    })

    test('wrap at both ends, because a radio group is a ring', () => {
        expect(paletteAfter('contrast', 'ArrowRight')).toBe('amber')
        expect(paletteAfter('amber', 'ArrowLeft')).toBe('contrast')
    })

    // Space and Enter choose what already has focus, and every other key is the browser's.
    test('answer nothing to a key this control does not move on', () => {
        for (const key of [' ', 'Enter', 'Tab', 'Escape', 'a']) {
            expect(paletteAfter('amber', key)).toBeNull()
        }
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
