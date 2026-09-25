import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

/**
 * A regenerated primitive that spells the class differently silently stops the growth.
 *
 * `index.css` grows a popup to its longest row only where it is still pinned to its anchor, and
 * the class the generated popup carries is what says so: `cn` merges that class away when a
 * screen gives its menu a width of its own. The class and the selector are one arrangement in
 * two files, and nothing else in a build fails when half of it moves.
 */

const INDEX_CSS = fileURLToPath(new URL('../index.css', import.meta.url))
const COMBOBOX = fileURLToPath(new URL('../components/ui/combobox.tsx', import.meta.url))
const DROPDOWN_MENU = fileURLToPath(new URL('../components/ui/dropdown-menu.tsx', import.meta.url))

/** The class a generated popup is pinned to its anchor with. */
const PINNED = 'w-(--anchor-width)'

/**
 * The classes the element carrying a slot is rendered with, one by one.
 *
 * Whole classes rather than a substring, because a variant of the same class --
 * `data-[chips=true]:min-w-(--anchor-width)` -- holds the pinned one inside it.
 */
function classesOf(file: string, slot: string): string[] {
    const source = readFileSync(file, 'utf8')
    const slotAt = source.indexOf(`data-slot="${slot}"`)
    if (slotAt === -1) throw new Error(`${file} no longer renders a ${slot}`)
    const opens = source.indexOf('className={cn("', slotAt)
    if (opens === -1) throw new Error(`${file} no longer gives its ${slot} a className`)
    const from = opens + 'className={cn("'.length
    return source.slice(from, source.indexOf('"', from)).split(/\s+/)
}

describe('a popup grows to its longest row', () => {
    test('the generated combobox popup is still pinned to its anchor', () => {
        expect(classesOf(COMBOBOX, 'combobox-content')).toContain(PINNED)
    })

    test('the generated dropdown menu popup is still pinned to its anchor', () => {
        expect(classesOf(DROPDOWN_MENU, 'dropdown-menu-content')).toContain(PINNED)
    })

    test('index.css grows exactly the popups that are still pinned', () => {
        const css = readFileSync(INDEX_CSS, 'utf8')
        expect(css).toContain(`[data-slot='combobox-content'][class~='${PINNED}']`)
        expect(css).toContain(`[data-slot='dropdown-menu-content'][class~='${PINNED}']`)
    })
})
