/**
 * Everything the settings dialog offers, as data.
 *
 * ROWS RATHER THAN PANES. A pane written as markup can only be searched by searching markup;
 * a row that is a record -- what it is called, what it is for, which category it is filed
 * under, what else it can be found by -- can be filtered by a pure function, and that function
 * is the whole of the search box. The control on the right of a row is the dialog's, keyed by
 * the row's id, so the registry stays free of React and is exercised in plain Node.
 *
 * THE SHORTCUT ROWS ARE NOT WRITTEN DOWN. `lib/shortcuts` already holds every key this app
 * answers, and a second list here would be a list that drifts. They are derived from it, which
 * is why building the registry needs to know what kind of keyboard this is.
 */

import { shortcuts } from '@/lib/shortcuts'

/** The headings the left nav lays categories out under. */
export interface SettingsGroup {
    id: string
    label: string
}

export const SETTINGS_GROUPS: readonly SettingsGroup[] = [
    { id: 'preferences', label: 'Preferences' },
    { id: 'you', label: 'You' },
    { id: 'instance', label: 'This instance' },
]

/** One entry in the left nav. */
export interface SettingsCategory {
    id: string
    label: string
    group: string
}

export const SETTINGS_CATEGORIES: readonly SettingsCategory[] = [
    { id: 'general', label: 'General', group: 'preferences' },
    { id: 'theme', label: 'Theme', group: 'preferences' },
    { id: 'shortcuts', label: 'Shortcuts', group: 'preferences' },
    { id: 'account', label: 'Account', group: 'you' },
    { id: 'server', label: 'Server', group: 'instance' },
]

/**
 * One row in the right pane: what it is called, what it can be found by, and the fact it adds.
 *
 * A DESCRIPTION IS A FACT OR IT IS NOTHING. A line restating the label is a line nobody reads,
 * so `description` is absent on almost every row and carries something the control cannot show
 * on the few that have one.
 */
export interface SettingsRow {
    id: string
    category: string
    label: string
    description?: string
    /** Extra words the search box matches on and nothing renders. */
    keywords?: string[]
}

/** Where the reader lands when the dialog opens with nothing chosen. */
export const FIRST_CATEGORY = 'general'

/**
 * Every row, in the order the panes lay them out.
 *
 * `apple` decides how a chord is spelled, which is a fact about the keyboard rather than about
 * the settings, and is passed in for the same reason `shortcuts` takes it.
 */
export function settingsRows(apple: boolean): SettingsRow[] {
    return [
        {
            id: 'theme:appearance',
            category: 'theme',
            label: 'Appearance',
            keywords: ['theme', 'mode', 'dark', 'light', 'system', 'colour', 'color'],
        },
        {
            id: 'theme:palette',
            category: 'theme',
            label: 'Palette',
            keywords: ['palette', 'theme', 'colour', 'color', 'paper', 'contrast', 'accessibility'],
        },
        {
            id: 'general:times',
            category: 'general',
            label: 'Timezone',
            description: 'Timestamps everywhere; a schedule keeps its own.',
            keywords: ['timezone', 'utc', 'clock', 'local', 'zone'],
        },
        {
            id: 'general:tails',
            category: 'general',
            label: 'Follow logs',
            keywords: ['logs', 'scroll', 'follow', 'tail', 'live'],
        },
        {
            id: 'account:identity',
            category: 'account',
            label: 'Signed in as',
            keywords: ['user', 'username', 'role', 'account', 'who'],
        },
        {
            id: 'account:password',
            category: 'account',
            label: 'Password',
            keywords: ['change', 'credentials', 'secret'],
        },
        {
            id: 'account:sign-out',
            category: 'account',
            label: 'Session',
            keywords: ['sign out', 'logout', 'leave', 'exit'],
        },
        ...shortcuts(apple).map((shortcut) => ({
            id: `shortcuts:${shortcut.id}`,
            category: 'shortcuts',
            label: shortcut.action,
            keywords: ['key', 'chord', 'keyboard', ...shortcut.keys],
        })),
        {
            id: 'server:health',
            category: 'server',
            label: 'Health',
            keywords: ['readiness', 'probe', 'recheck', 'ready', 'status'],
        },
        {
            id: 'server:version',
            category: 'server',
            label: 'Version',
            keywords: ['release', 'build'],
        },
        {
            id: 'server:environment',
            category: 'server',
            label: 'Environment',
            keywords: ['dev', 'production', 'staging'],
        },
        {
            id: 'server:database',
            category: 'server',
            label: 'Database',
            keywords: ['sqlite', 'postgres', 'postgresql'],
        },
        {
            id: 'server:blocks',
            category: 'server',
            label: 'Blocks',
            keywords: ['catalog', 'steps', 'plugins'],
        },
        {
            id: 'server:storage',
            category: 'server',
            label: 'Storage',
            keywords: ['s3', 'file', 'artifacts', 'uri', 'schemes'],
        },
        {
            id: 'server:plugins',
            category: 'server',
            label: 'Plugins',
            keywords: ['extensions', 'packages', 'installed'],
        },
    ]
}

/** Every word a row can be found by, lowercased. */
function haystack(row: SettingsRow, categories: readonly SettingsCategory[]): string {
    const category = categories.find((one) => one.id === row.category)
    return [row.label, row.description ?? '', category?.label ?? '', ...(row.keywords ?? [])]
        .join(' ')
        .toLowerCase()
}

/**
 * The rows one query names, in the order they were registered.
 *
 * EVERY TERM HAS TO MATCH, the way the command palette's filter works, so typing more words
 * narrows. An empty query is not a filter and answers everything, which is what a dialog opened
 * with no intention should show. There is no ranking: these rows are laid out under headings
 * and reordering them would move a control out from under the heading that explains it.
 */
export function filterSettings(
    rows: readonly SettingsRow[],
    query: string,
    categories: readonly SettingsCategory[] = SETTINGS_CATEGORIES,
): SettingsRow[] {
    const trimmed = query.trim().toLowerCase()
    if (trimmed === '') return [...rows]
    const terms = trimmed.split(/\s+/)
    return rows.filter((row) => {
        const words = haystack(row, categories)
        return terms.every((term) => words.includes(term))
    })
}

/** The categories that still hold a row, which is what the left nav lists while a query narrows. */
export function categoriesWith(
    rows: readonly SettingsRow[],
    categories: readonly SettingsCategory[] = SETTINGS_CATEGORIES,
): SettingsCategory[] {
    const held = new Set(rows.map((row) => row.category))
    return categories.filter((category) => held.has(category.id))
}

/** The rows of one category, which is one pane of the dialog. */
export function rowsOf(rows: readonly SettingsRow[], category: string): SettingsRow[] {
    return rows.filter((row) => row.category === category)
}
