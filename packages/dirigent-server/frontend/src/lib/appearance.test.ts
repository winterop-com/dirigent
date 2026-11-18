import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'

import { FACES, THEMES } from '@winterop-com/sokkel-ui/lib/appearance'
import { describe, expect, test } from 'vitest'

import { APPEARANCE_DEFAULTS, APPEARANCE_OFFER, APPEARANCE_THEMES, CARRIED_THEMES } from '@/lib/appearance'

const INDEX_HTML = fileURLToPath(new URL('../../index.html', import.meta.url))
const INDEX_CSS = fileURLToPath(new URL('../index.css', import.meta.url))

/** The `<script>` tags in index.html, in document order. */
function scriptTags(html: string): string[] {
    return [...html.matchAll(/<script\b[^>]*>/g)].map((match) => match[0])
}

/** The pre-paint script's tag. */
function prePaint(): string {
    const tag = scriptTags(readFileSync(INDEX_HTML, 'utf8')).find((one) => one.includes('/appearance.js'))
    expect(tag).toBeDefined()
    return tag ?? ''
}

describe('the pre-paint script', () => {
    // With nothing stored, the script paints its own defaults and the app then wears
    // `APPEARANCE_DEFAULTS`; two different answers flash one look into the other.
    test('starts in the look the app starts in', () => {
        expect(/data-theme="([^"]*)"/.exec(prePaint())?.[1]).toBe(APPEARANCE_DEFAULTS.theme)
        expect(/data-scheme="([^"]*)"/.exec(prePaint())?.[1]).toBe(APPEARANCE_DEFAULTS.scheme)
    })

    // A stored theme outside the offered ones gives way before the first paint only if the script
    // offers the same themes the app does.
    test('offers the themes the app offers', () => {
        expect(/data-themes="([^"]*)"/.exec(prePaint())?.[1].split(' ')).toEqual(CARRIED_THEMES)
        expect(APPEARANCE_OFFER.themes).toEqual(CARRIED_THEMES)
    })

    test('is the first script the document loads, and a classic one', () => {
        const [first] = scriptTags(readFileSync(INDEX_HTML, 'utf8'))
        expect(first).toContain('src="/appearance.js"')
        for (const attribute of ['type=', 'async', 'defer']) expect(first).not.toContain(attribute)
    })
})

describe('the carried themes', () => {
    test("are the library's own, in its order, the default among them", () => {
        expect(APPEARANCE_THEMES.map((theme) => theme.value)).toEqual(
            THEMES.map((theme) => theme.value).filter((name) => CARRIED_THEMES.includes(name)),
        )
        expect(APPEARANCE_THEMES).toHaveLength(CARRIED_THEMES.length)
        expect(CARRIED_THEMES).toContain(APPEARANCE_DEFAULTS.theme)
    })

    // A theme paints only once its file is imported.
    test('each has its file imported in index.css', () => {
        const css = readFileSync(INDEX_CSS, 'utf8')
        for (const name of CARRIED_THEMES) {
            expect(
                createRequire(import.meta.url).resolve(`@winterop-com/sokkel-ui/themes/${name}.css`),
            ).toBeTruthy()
            expect(css).toContain(`@import '@winterop-com/sokkel-ui/themes/${name}.css';`)
        }
    })
})

describe('the offered typefaces', () => {
    // Settings offers every library typeface; one whose files are not imported falls back unseen.
    test('have their faces imported in index.css', () => {
        const css = readFileSync(INDEX_CSS, 'utf8')
        expect(Object.keys(FACES)).toEqual(['geist', 'system'])
        expect(css).toContain("@import '@fontsource-variable/geist';")
        expect(css).toContain("@import '@fontsource-variable/geist-mono';")
    })
})
