import { filterSettings } from '@winterop-com/sokkel-ui/SettingsDialog'
import { describe, expect, test } from 'vitest'

import {
    FIRST_CATEGORY,
    SETTINGS_CATEGORIES,
    SETTINGS_GROUPS,
    settingsGroups,
    settingsRows,
    type SettingsRow,
} from '@/lib/settings'
import { shortcuts } from '@/lib/shortcuts'

const ROWS = settingsRows(false)
const GROUPS = settingsGroups(ROWS, () => ({ control: null }))

function inCategory(rows: readonly SettingsRow[], category: string): SettingsRow[] {
    return rows.filter((row) => row.category === category)
}

/** The ids of the rows a search keeps, in the order the dialog lays them out. */
function found(search: string): string[] {
    return filterSettings(GROUPS, search).flatMap((group) =>
        group.sections.flatMap((section) => section.settings.map((setting) => setting.id)),
    )
}

/** The categories a search leaves in the nav. */
function sectionsFound(search: string): string[] {
    return filterSettings(GROUPS, search).flatMap((group) => group.sections.map((section) => section.id))
}

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

    test('lists exactly the shortcuts this app answers, and does not hold its own list', () => {
        const listed = inCategory(ROWS, 'shortcuts').map((row) => row.label)
        expect(listed).toEqual(shortcuts(false).map((one) => one.action))
    })

    test('spells a chord the way the keyboard in front of somebody spells it', () => {
        const apple = inCategory(settingsRows(true), 'shortcuts')
        const other = inCategory(settingsRows(false), 'shortcuts')
        expect(apple[0].keywords).toContain('⌘')
        expect(other[0].keywords).toContain('Ctrl')
    })

    test('carries a description only where it states a fact the control cannot', () => {
        const described = ROWS.filter((row) => row.description !== undefined).map((row) => row.id)
        expect(described).toEqual(['general:times', 'general:highlight'])
    })
})

describe("the library's groups", () => {
    test('are Preferences, You and This instance, each category a section in the nav order', () => {
        expect(GROUPS.map((group) => group.title)).toEqual(SETTINGS_GROUPS.map((group) => group.label))
        expect(GROUPS.flatMap((group) => group.sections.map((section) => section.id))).toEqual(
            SETTINGS_CATEGORIES.map((category) => category.id),
        )
    })

    test('carry every row once, in the order the registry holds them within a category', () => {
        for (const category of SETTINGS_CATEGORIES) {
            const section = GROUPS.flatMap((group) => group.sections).find((one) => one.id === category.id)
            expect(section?.settings.map((setting) => setting.id)).toEqual(
                inCategory(ROWS, category.id).map((row) => row.id),
            )
        }
    })

    test('put the control the dialog chooses on each row', () => {
        const groups = settingsGroups(ROWS, (row) => ({
            control: row.id,
            layout: 'trailing',
        }))
        const setting = groups[0].sections[0].settings[0]
        expect(setting.control).toBe(setting.id)
        expect(setting.layout).toBe('trailing')
    })

    test('leave out a category with no row', () => {
        const groups = settingsGroups(inCategory(ROWS, 'theme'), () => ({
            control: null,
        }))
        expect(groups.map((group) => group.id)).toEqual(['preferences'])
        expect(groups[0].sections.map((section) => section.id)).toEqual(['theme'])
    })
})

describe('the search box over these rows', () => {
    test('finds a row by a word in its own name', () => {
        expect(found('appearance')).toEqual(['theme:appearance'])
    })

    test('finds a row by a word nothing renders', () => {
        expect(found('timezone')).toEqual(['general:times'])
        expect(found('openapi')).toEqual(['server:reference'])
    })

    test('finds every row of a category by its name', () => {
        expect(found('account')).toEqual(inCategory(ROWS, 'account').map((row) => row.id))
    })

    test('reaches across categories, which is the whole point of one box', () => {
        expect(sectionsFound('palette')).toEqual(['theme', 'shortcuts'])
    })

    test('every term has to match, so typing more words narrows', () => {
        expect(found('password change')).toEqual(['account:password'])
    })

    test('a query nothing matches answers nothing rather than everything', () => {
        expect(found('stroopwafel')).toEqual([])
    })
})
