import { describe, expect, test } from 'vitest'

import {
    categoriesWith,
    FIRST_CATEGORY,
    filterSettings,
    rowsOf,
    SETTINGS_CATEGORIES,
    SETTINGS_GROUPS,
    settingsRows,
} from '@/lib/settings'
import { shortcuts } from '@/lib/shortcuts'

const ROWS = settingsRows(false)

describe('the settings registry', () => {
    test('files every row under a category the left nav has', () => {
        const known = new Set(SETTINGS_CATEGORIES.map((category) => category.id))
        for (const row of ROWS) expect(known.has(row.category)).toBe(true)
    })

    test('files every category under a group the left nav has', () => {
        const known = new Set(SETTINGS_GROUPS.map((group) => group.id))
        for (const category of SETTINGS_CATEGORIES) expect(known.has(category.group)).toBe(true)
    })

    test('opens on a category that exists', () => {
        expect(SETTINGS_CATEGORIES.map((category) => category.id)).toContain(FIRST_CATEGORY)
    })

    test('gives every row an id of its own, because the control on its right is keyed by it', () => {
        expect(new Set(ROWS.map((row) => row.id)).size).toBe(ROWS.length)
    })

    // The shortcut rows are derived rather than written down: a shortcut added to lib/shortcuts
    // appears here without anybody editing this registry, and this fails if it stops being so.
    test('lists exactly the shortcuts this app answers, and does not hold its own list', () => {
        const listed = rowsOf(ROWS, 'shortcuts').map((row) => row.label)
        expect(listed).toEqual(shortcuts(false).map((one) => one.action))
    })

    // The keys are drawn as chips by the pane and are searchable here, which is why they are
    // keywords rather than a description: a row's description is a fact, or it is absent.
    test('spells a chord the way the keyboard in front of somebody spells it', () => {
        const apple = rowsOf(settingsRows(true), 'shortcuts')
        const other = rowsOf(settingsRows(false), 'shortcuts')
        expect(apple[0].keywords).toContain('⌘')
        expect(other[0].keywords).toContain('Ctrl')
    })

    test('carries a description only where it states a fact the control cannot', () => {
        const described = ROWS.filter((row) => row.description !== undefined).map((row) => row.id)
        expect(described).toEqual(['general:times'])
    })
})

describe('the search box', () => {
    test('an empty query is not a filter and answers every row in order', () => {
        expect(filterSettings(ROWS, '')).toEqual(ROWS)
        expect(filterSettings(ROWS, '   ')).toHaveLength(ROWS.length)
    })

    test('finds a row by a word in its own name', () => {
        expect(filterSettings(ROWS, 'appearance').map((row) => row.id)).toEqual(['theme:appearance'])
    })

    test('finds a row by a word nothing renders', () => {
        expect(filterSettings(ROWS, 'timezone').map((row) => row.id)).toEqual(['general:times'])
    })

    test('finds a row by the category it is filed under', () => {
        expect(filterSettings(ROWS, 'account').every((row) => row.category === 'account')).toBe(true)
    })

    test('reaches across categories, which is the whole point of one box', () => {
        const found = filterSettings(ROWS, 'palette')
        expect(new Set(found.map((row) => row.category))).toEqual(new Set(['theme', 'shortcuts']))
    })

    test('every term has to match, so typing more words narrows', () => {
        const one = filterSettings(ROWS, 'password')
        const two = filterSettings(ROWS, 'password change')
        expect(two.length).toBeLessThanOrEqual(one.length)
        expect(two.map((row) => row.id)).toEqual(['account:password'])
    })

    test('is not case sensitive', () => {
        expect(filterSettings(ROWS, 'UTC')).toEqual(filterSettings(ROWS, 'utc'))
    })

    test('a query nothing matches answers nothing rather than everything', () => {
        expect(filterSettings(ROWS, 'stroopwafel')).toEqual([])
    })

    test('does not reorder what it keeps, because a row sits under the heading that explains it', () => {
        const kept = filterSettings(ROWS, 'the')
        expect(kept).toEqual(ROWS.filter((row) => kept.includes(row)))
    })
})

describe('the left nav while a query narrows', () => {
    test('lists only the categories that still hold a row', () => {
        const found = filterSettings(ROWS, 'appearance')
        expect(categoriesWith(found).map((category) => category.id)).toEqual(['theme'])
    })

    test('lists nothing when nothing matches', () => {
        expect(categoriesWith(filterSettings(ROWS, 'stroopwafel'))).toEqual([])
    })

    test('keeps the nav order rather than the order rows happened to match in', () => {
        const every = categoriesWith(ROWS).map((category) => category.id)
        expect(every).toEqual(SETTINGS_CATEGORIES.map((category) => category.id))
    })
})
