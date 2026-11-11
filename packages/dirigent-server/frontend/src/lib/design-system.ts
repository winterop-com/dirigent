/**
 * The decisions the design-system components make, as pure functions, and the words sokkel-ui's
 * components say here.
 *
 * A component draws; what it says and when a word appears beside a dot are decided here, where a
 * Node test can hold them.
 */

import type { AccountMenuWords } from '@winterop-com/sokkel-ui/AccountMenu'
import type { ChipWords } from '@winterop-com/sokkel-ui/Chip'
import type { CommandPaletteWords } from '@winterop-com/sokkel-ui/CommandPalette'
import type { CodeSchemaWords } from '@winterop-com/sokkel-ui/CodeEditor'
import type { CopyButtonWords } from '@winterop-com/sokkel-ui/CopyButton'
import type { DialogShellWords } from '@winterop-com/sokkel-ui/DialogShell'
import type { DotProps } from '@winterop-com/sokkel-ui/Dot'
import type { FieldWords } from '@winterop-com/sokkel-ui/Field'
import type { RailWords } from '@winterop-com/sokkel-ui/Rail'
import type { SchemeChoiceWords } from '@winterop-com/sokkel-ui/SchemeChoice'
import type { SearchFieldWords } from '@winterop-com/sokkel-ui/SearchField'
import type { SecretRevealWords } from '@winterop-com/sokkel-ui/SecretReveal'
import type { ServerMenuWords } from '@winterop-com/sokkel-ui/ServerMenu'
import type { ShellWords } from '@winterop-com/sokkel-ui/Shell'
import type { SettingsDialogWords } from '@winterop-com/sokkel-ui/SettingsDialog'
import type { SidePanelWords } from '@winterop-com/sokkel-ui/SidePanel'
import type { TopBarWords } from '@winterop-com/sokkel-ui/TopBar'
import type { ShortcutsDialogWords } from '@winterop-com/sokkel-ui/ShortcutsDialog'
import type { SignInWords } from '@winterop-com/sokkel-ui/SignIn'
import type { SplitButtonWords } from '@winterop-com/sokkel-ui/SplitButton'
import type { ThemeCardsWords } from '@winterop-com/sokkel-ui/ThemeCards'
import type { TextLinkWords } from '@winterop-com/sokkel-ui/TextLink'
import type { ToolbarWords } from '@winterop-com/sokkel-ui/Toolbar'
import type { WindowedPaneWords } from '@winterop-com/sokkel-ui/WindowedPane'

import { LABELS } from '@/lib/labels'
import { PAGE } from '@/lib/paging'
import { statusLabel, statusTokens } from '@/lib/status'

/** What a dot or a notice says about something that is not a run: how it is, in one hue. */
export type Tone = 'good' | 'critical' | 'warning' | 'info' | 'quiet' | 'unknown'

/** The one map from a tone to the token it is filled with. `unknown` is drawn hollow. */
export const TONE_FILL: Readonly<Record<Tone, string>> = {
    good: 'var(--good)',
    critical: 'var(--critical)',
    warning: 'var(--warning)',
    info: 'var(--info)',
    quiet: 'var(--faint)',
    unknown: 'var(--faint)',
}

/** The tones that are news: a dot in one of these says its word beside it, not only on hover. */
export const NEWS_TONES: ReadonlySet<Tone> = new Set(['critical', 'unknown'])

/** The run and attempt states that are news, read the same way. */
export const NEWS_STATUSES: ReadonlySet<string> = new Set(['failed', 'completed_with_errors'])

/** When a dot spells its word: only when it is news, always, or never. */
export type Say = 'news' | 'always' | 'never'

/**
 * Whether a dot draws its word beside it.
 *
 * A green dot alone says connected; a word appears where the state is news. The word is the
 * dot's accessible name and its tooltip either way.
 */
export function saysWord(news: boolean, say: Say = 'news'): boolean {
    if (say === 'always') return true
    if (say === 'never') return false
    return news
}

/** Whether a tone or a status is news. */
export function isNews(dot: { tone: Tone } | { status: string }): boolean {
    return 'tone' in dot ? NEWS_TONES.has(dot.tone) : NEWS_STATUSES.has(dot.status)
}

/**
 * How a dot is drawn for a tone or a run or attempt status: 8px, filled from the one map, an
 * `unknown` tone hollow, named by its word, and saying that word beside it only when it is news. A
 * dot that does not say its word says it as its tooltip. A word it says is small, and in body ink
 * only for a failure: a state nothing has proved is said quietly.
 */
export function dotOf(
    dot: { tone: Tone; label: string } | { status: string; label?: string },
    say?: Say,
): DotProps {
    const label = dot.label ?? ('status' in dot ? statusLabel(dot.status) : '')
    const said = saysWord(isNews(dot), say)
    const loud = isNews(dot) && !('tone' in dot && dot.tone === 'unknown')
    return {
        color: 'tone' in dot ? TONE_FILL[dot.tone] : statusTokens(dot.status)['--chip'],
        outline: 'tone' in dot && dot.tone === 'unknown',
        size: 'md',
        label,
        say: said,
        tip: said ? undefined : label,
        className: said
            ? loud
                ? 'text-xs font-medium text-foreground'
                : 'text-xs text-muted-foreground'
            : undefined,
    }
}

/** What a field says beside its label when it is required. */
export const FIELD_WORDS: FieldWords = { required: LABELS.form.required }

/** What a chip's remove button is called, as a function of the chip's words: "Stop filtering by finance". */
export function chipWords(remove: (text: string) => string): ChipWords {
    return { remove }
}

/** What a copy button is called before a press, `copy`, and for a moment after it. */
export function copyWords(copy: string): CopyButtonWords {
    return { copy, copied: LABELS.action.copy.done }
}

/** What a secret shown once says: its name, its copy button named for it, and that it is shown once. */
export function secretWords(noun: string): SecretRevealWords {
    return { ...copyWords(LABELS.shell.copy_secret(noun)), warning: LABELS.shell.shown_once, secret: noun }
}

/** What a search box says while it is empty, wherever one is drawn. */
export const SEARCH_PLACEHOLDER = LABELS.shell.search

/** What a search box's clear button is called. */
export const SEARCH_WORDS: SearchFieldWords = { clear: LABELS.shell.clear_search }

/**
 * How every listing's `DataTable` lays out: the list look, columns that do not drag, and its rows
 * as cards once its own box is narrower than `lg` and than the least its columns take, which
 * is never under 36rem. The next page is asked for as the rows near the end of the box.
 */
export const LISTING = {
    variant: 'list',
    resizable: false,
    stackBelow: '64rem',
    minWidth: '36rem',
} as const

/**
 * A listing set in a `Section` among others: unframed, and growing with its rows rather than
 * scrolling in a box of its own, so the next page is a button after the last row.
 */
export const SECTION_LISTING = {
    ...LISTING,
    framed: false,
    loadMore: 'button',
    loadMoreCount: PAGE,
    words: { loadMore: (count: number | undefined) => LABELS.shell.load_more(String(count ?? PAGE)) },
} as const

/** The one dismissal word a dialog's footer says. */
export const DIALOG_WORDS: Partial<DialogShellWords> = { cancel: LABELS.action.cancel }

/** What a link out of this app says to a screen reader after its text. */
export const LINK_WORDS: TextLinkWords = { newTab: LABELS.shell.new_tab }

/** What a split button's chevron is called: "More ways to create a pipeline". */
export function splitWords(more: string): SplitButtonWords {
    return { more }
}

/** What a strip of verbs says: the menu the ones without room fold into, and a split verb's chevron. */
export const TOOLBAR_WORDS: ToolbarWords = {
    more: LABELS.shell.more_actions,
    moreWays: LABELS.shell.more_ways,
}

/** What a pane's window button and its window's close say, the button naming the pane. */
export function windowWords(name: string): Partial<WindowedPaneWords> {
    return { expand: LABELS.shell.open_in_window(name), close: LABELS.shell.close_window }
}

/** What the sign-in screen says: its title and button, its two fields, the reveal toggle and the seam. No placeholders: the labels name the fields. */
export const SIGN_IN_WORDS: Partial<SignInWords> = {
    title: LABELS.action.sign_in.verb,
    submit: LABELS.action.sign_in.verb,
    busy: LABELS.action.sign_in.busy,
    user: LABELS.word.username,
    password: LABELS.word.password,
    show: LABELS.login.show_password,
    hide: LABELS.login.hide_password,
    seam: LABELS.login.seam,
}

/** What an editor's schema check says that is not an issue: the word beside a deprecated key. */
export const SCHEMA_CHECK_WORDS: Partial<CodeSchemaWords> = { deprecated: LABELS.editor.deprecated_key }

/**
 * How a verb is shut: with its sentence where there is one, which keeps it reachable and says why,
 * and quietly where there is none, as while its own request is in flight.
 */
export function shutWith(shut: boolean, why?: string | null): { disabled?: boolean; reason?: string } {
    if (!shut) return {}
    return why === undefined || why === null ? { disabled: true } : { reason: why }
}

/** One section of the gallery, by the id its heading and its index entry share. */
export type GallerySection =
    | 'titles'
    | 'headings'
    | 'links'
    | 'labels'
    | 'dots'
    | 'icons'
    | 'buttons'
    | 'search'
    | 'forms'
    | 'switches'
    | 'notices'
    | 'dialogs'
    | 'facts'

/** The gallery's index: what somebody is looking for, in the order the page draws it. */
export const GALLERY_INDEX: readonly {
    group: 'text' | 'marks' | 'controls' | 'containers'
    sections: readonly GallerySection[]
}[] = [
    { group: 'text', sections: ['titles', 'headings', 'links'] },
    { group: 'marks', sections: ['labels', 'dots', 'icons'] },
    { group: 'controls', sections: ['buttons', 'search', 'forms', 'switches'] },
    { group: 'containers', sections: ['notices', 'dialogs', 'facts'] },
]

/** The anchor of one gallery section, which is what its index entry links to. */
export function galleryAnchor(section: GallerySection): string {
    return `ds-${section}`
}

/** What the frame says: the drawer's button and its close, the panel's toggle, and its own two keys. */
export const SHELL_WORDS: Partial<ShellWords> = {
    menu: LABELS.shell.open_nav,
    close: LABELS.shell.close_nav,
    showPanel: LABELS.shell.show_panel,
    hidePanel: LABELS.shell.hide_panel,
    openPalette: LABELS.shell.open_palette,
    openShortcuts: LABELS.shell.chord.shortcuts,
    panelTabs: LABELS.shell.panel_tabs,
}

/** What the top bar's palette button and trail are called. */
export const TOP_BAR_WORDS: Partial<TopBarWords> = {
    search: LABELS.shell.palette_button,
    palette: LABELS.shell.open_palette,
    trail: LABELS.shell.breadcrumb,
}

/** What the top bar's instance dot is called, before the state it says, and when it was last asked. */
export const SERVER_MENU_WORDS: Partial<ServerMenuWords> = {
    label: LABELS.shell.instance.label,
    checking: LABELS.state.server.asking,
    checkedAt: LABELS.shell.instance.checked_at,
}

/** What the right panel's edge is called. */
export const SIDE_PANEL_WORDS: Partial<SidePanelWords> = {
    resize: LABELS.shell.resize_panel,
}

/** What the rail's head and edge are called. */
export const RAIL_WORDS: Partial<RailWords> = {
    collapse: LABELS.shell.collapse_nav,
    expand: LABELS.shell.expand_nav,
    resize: LABELS.shell.resize_nav,
}

/** What the command palette says. */
export const PALETTE_WORDS: CommandPaletteWords = {
    title: LABELS.palette.title,
    placeholder: LABELS.palette.placeholder,
    empty: LABELS.palette.empty,
    close: LABELS.palette.close,
    open: LABELS.palette.verb,
    palette: LABELS.palette.title,
}

/** What the shortcuts dialog says. */
export const SHORTCUTS_WORDS: ShortcutsDialogWords = {
    title: LABELS.shell.shortcuts,
    general: LABELS.shell.shortcuts_general,
    sequence: LABELS.shell.shortcuts_sequence,
}

/** What the account menu says, its control named for the account it stands for. */
export function accountWords(username: string): Partial<AccountMenuWords> {
    return {
        account: LABELS.shell.account.label(username),
        settings: LABELS.shell.settings,
        shortcuts: LABELS.shell.account.shortcuts,
        scheme: LABELS.shell.account.appearance,
        light: LABELS.shell.mode.light,
        dark: LABELS.shell.mode.dark,
        system: LABELS.shell.mode.system,
        signOut: LABELS.action.sign_out,
    }
}

/** What the settings dialog says: its title, its search, the footer's note and Done, and its two ways out. */
export const SETTINGS_WORDS: Partial<SettingsDialogWords> = {
    title: LABELS.settings.title,
    search: SEARCH_PLACEHOLDER,
    searchLabel: LABELS.settings.search,
    clear: LABELS.shell.clear_search,
    noMatch: LABELS.settings.no_match,
    saved: LABELS.settings.saved,
    done: LABELS.settings.done,
    close: LABELS.settings.close,
    back: LABELS.settings.back,
}

/** What the Theme pane's mode control says: the row it is, and its three settings. */
export const SCHEME_WORDS: SchemeChoiceWords = {
    scheme: LABELS.settings.row.appearance,
    system: LABELS.shell.mode.system,
    light: LABELS.shell.mode.light,
    dark: LABELS.shell.mode.dark,
}

/** What the Theme pane's palette cards are called, for a screen reader. */
export const THEME_CARDS_WORDS: ThemeCardsWords = { theme: LABELS.settings.row.palette }
