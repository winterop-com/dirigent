/**
 * Everything the settings dialog offers, as data.
 *
 * Every row is a record -- what it is called, which category it is filed under, what else it can
 * be found by -- and sokkel-ui's settings dialog searches those records. The control on a row is
 * the dialog's, keyed by the row's id, so this module holds no React and runs in plain Node.
 *
 * The shortcut rows are derived from `lib/shortcuts`, which is why building the rows needs to know
 * what kind of keyboard this is.
 */

import type { Setting, SettingsGroup } from '@winterop-com/sokkel-ui/SettingsDialog'

import { LABELS } from '@/lib/labels'
import { shortcuts } from '@/lib/shortcuts'

/** The headings the left nav lays categories out under. */
export interface SettingsHeading {
    id: string
    label: string
}

export const SETTINGS_GROUPS: readonly SettingsHeading[] = [
    { id: 'preferences', label: LABELS.settings.group.preferences },
    { id: 'you', label: LABELS.settings.group.you },
    { id: 'instance', label: LABELS.settings.group.instance },
]

/** One entry in the left nav. */
export interface SettingsCategory {
    id: string
    label: string
    group: string
}

export const SETTINGS_CATEGORIES: readonly SettingsCategory[] = [
    { id: 'general', label: LABELS.settings.category.general, group: 'preferences' },
    { id: 'theme', label: LABELS.settings.category.theme, group: 'preferences' },
    { id: 'shortcuts', label: LABELS.settings.category.shortcuts, group: 'preferences' },
    { id: 'account', label: LABELS.word.account.label, group: 'you' },
    { id: 'server', label: LABELS.settings.category.server, group: 'instance' },
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
            label: LABELS.settings.row.appearance,
            keywords: ['theme', 'mode', 'dark', 'light', 'system', 'colour', 'color'],
        },
        {
            id: 'theme:palette',
            category: 'theme',
            label: LABELS.settings.row.palette,
            keywords: ['palette', 'theme', 'colour', 'color', 'paper', 'contrast', 'accessibility'],
        },
        {
            id: 'general:times',
            category: 'general',
            label: LABELS.word.timezone,
            description: LABELS.settings.description.timezone,
            keywords: ['timezone', 'utc', 'clock', 'local', 'zone'],
        },
        {
            id: 'general:tails',
            category: 'general',
            label: LABELS.settings.row.follow_logs,
            keywords: ['logs', 'scroll', 'follow', 'tail', 'live'],
        },
        {
            id: 'general:highlight',
            category: 'general',
            label: LABELS.settings.row.current_line,
            description: LABELS.settings.description.current_line,
            keywords: ['editor', 'caret', 'cursor', 'row', 'line', 'highlight', 'source'],
        },
        {
            id: 'account:identity',
            category: 'account',
            label: LABELS.settings.row.signed_in_as,
            keywords: ['user', 'username', 'role', 'account', 'who'],
        },
        {
            id: 'account:password',
            category: 'account',
            label: LABELS.word.password,
            keywords: ['change', 'credentials', 'secret'],
        },
        {
            id: 'account:sign-out',
            category: 'account',
            label: LABELS.settings.row.session,
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
            label: LABELS.word.health,
            keywords: ['readiness', 'probe', 'recheck', 'ready', 'status'],
        },
        {
            id: 'server:version',
            category: 'server',
            label: LABELS.word.version.label,
            keywords: ['release', 'build'],
        },
        {
            id: 'server:environment',
            category: 'server',
            label: LABELS.word.environment.label,
            keywords: ['dev', 'production', 'staging'],
        },
        {
            id: 'server:database',
            category: 'server',
            label: LABELS.word.database,
            keywords: ['sqlite', 'postgres', 'postgresql'],
        },
        {
            id: 'server:blocks',
            category: 'server',
            label: LABELS.word.block.heading,
            keywords: ['catalog', 'steps', 'plugins'],
        },
        {
            id: 'server:storage',
            category: 'server',
            label: LABELS.word.storage,
            keywords: ['s3', 'file', 'artifacts', 'uri', 'schemes'],
        },
        {
            id: 'server:plugins',
            category: 'server',
            label: LABELS.word.plugin.heading,
            keywords: ['extensions', 'packages', 'installed'],
        },
        {
            id: 'server:reference',
            category: 'server',
            label: LABELS.settings.row.reference,
            keywords: ['docs', 'documentation', 'api', 'openapi', 'help', 'manual'],
        },
    ]
}

/** What the dialog puts on one row besides its words: its control, and where that control sits. */
export type RowControl = Pick<Setting, 'control' | 'layout'>

/**
 * The rows as sokkel-ui's settings take them: the groups, each category a section under its group,
 * and each row a setting with the control `controlOf` puts on it. A group or a category with no row
 * is left out, so the nav never lists a destination with nothing in it.
 */
export function settingsGroups(
    rows: readonly SettingsRow[],
    controlOf: (row: SettingsRow) => RowControl,
): SettingsGroup[] {
    return SETTINGS_GROUPS.map((group) => ({
        id: group.id,
        title: group.label,
        sections: SETTINGS_CATEGORIES.filter((category) => category.group === group.id)
            .map((category) => ({
                id: category.id,
                label: category.label,
                settings: rows
                    .filter((row) => row.category === category.id)
                    .map((row) => {
                        const { control, layout } = controlOf(row)
                        return {
                            id: row.id,
                            title: row.label,
                            description: row.description,
                            keywords: row.keywords,
                            control,
                            layout,
                        }
                    }),
            }))
            .filter((section) => section.settings.length > 0),
    })).filter((group) => group.sections.length > 0)
}
