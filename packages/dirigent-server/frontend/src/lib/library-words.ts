/**
 * What sokkel-ui's components say in this app, and the props every screen hands one of them.
 *
 * The library draws and speaks English by default; each bundle here is its words read from the
 * catalogue, or a layout every listing of one shape shares, so a screen spreads one name rather
 * than spelling the props again.
 */

import type { AccountMenuWords } from '@winterop-com/sokkel-ui/AccountMenu'
import type { ChipWords } from '@winterop-com/sokkel-ui/Chip'
import type { CommandPaletteWords } from '@winterop-com/sokkel-ui/CommandPalette'
import type { CodeSchemaWords } from '@winterop-com/sokkel-ui/CodeEditor'
import type { CopyButtonWords } from '@winterop-com/sokkel-ui/CopyButton'
import type { DataTableWords } from '@winterop-com/sokkel-ui/DataTable'
import type { DialogShellWords } from '@winterop-com/sokkel-ui/DialogShell'
import type { DiffViewWords } from '@winterop-com/sokkel-ui/DiffView'
import type { FieldWords } from '@winterop-com/sokkel-ui/Field'
import type { FilePreviewWords } from '@winterop-com/sokkel-ui/FilePreview'
import type { FilterChipWords } from '@winterop-com/sokkel-ui/FilterChip'
import type { AsyncSelectWords } from '@winterop-com/sokkel-ui/AsyncSelect'
import type { BlockPickerWords } from '@winterop-com/sokkel-ui-graph/BlockPicker'
import type { GraphLayoutMenuWords } from '@winterop-com/sokkel-ui-graph/GraphLayoutMenu'
import type { RunGraphProps } from '@winterop-com/sokkel-ui-graph/RunGraph'
import type { PlainMarkdownProps } from '@winterop-com/sokkel-ui/PlainMarkdown'
import type { RailWords } from '@winterop-com/sokkel-ui/Rail'
import type { SchemeChoiceWords } from '@winterop-com/sokkel-ui/SchemeChoice'
import type { SchemaFormWords } from '@winterop-com/sokkel-ui/schema/SchemaForm'
import { literal } from '@winterop-com/sokkel-ui/schema/read'
import type { SearchFieldWords } from '@winterop-com/sokkel-ui/SearchField'
import type { SecretFieldWords } from '@winterop-com/sokkel-ui/SecretField'
import type { SecretRevealWords } from '@winterop-com/sokkel-ui/SecretReveal'
import type { ServerMenuWords } from '@winterop-com/sokkel-ui/ServerMenu'
import type { ShellWords } from '@winterop-com/sokkel-ui/Shell'
import type { SettingsDialogWords } from '@winterop-com/sokkel-ui/SettingsDialog'
import type { SidePanelWords } from '@winterop-com/sokkel-ui/SidePanel'
import type { TopBarWords } from '@winterop-com/sokkel-ui/TopBar'
import type { ShortcutsDialogWords } from '@winterop-com/sokkel-ui/ShortcutsDialog'
import type { SignInWords } from '@winterop-com/sokkel-ui/SignIn'
import type { SplitButtonWords } from '@winterop-com/sokkel-ui/SplitButton'
import type { TagChipsWords } from '@winterop-com/sokkel-ui/TagChips'
import type { ThemeCardsWords } from '@winterop-com/sokkel-ui/ThemeCards'
import type { TextLinkWords } from '@winterop-com/sokkel-ui/TextLink'
import type { ToolbarWords } from '@winterop-com/sokkel-ui/Toolbar'
import type { WindowedPaneWords } from '@winterop-com/sokkel-ui/WindowedPane'

import { counted, type Counted, LABELS } from '@/lib/labels'
import { PAGE, rowsRead } from '@/lib/paging'

/** What a picker over a held list says: its search box named for what it narrows by. */
export function pickerWords(search: string): Partial<AsyncSelectWords> {
    return { placeholder: LABELS.shell.choose, search, empty: LABELS.shell.no_match }
}

/** What a screen reader hears before an error and before a warning, wherever an issue is marked. */
const ISSUE_WORDS: Pick<FieldWords, 'issueCritical' | 'issueWarning'> = {
    issueCritical: LABELS.form.issue_critical,
    issueWarning: LABELS.form.issue_warning,
}

/** What a field says beside its label when it is required, and before its issues. */
export const FIELD_WORDS: FieldWords = { required: LABELS.form.required, ...ISSUE_WORDS }

/** What a password box says: the required word, and its Show and Hide. */
export const SECRET_FIELD_WORDS: Partial<SecretFieldWords> = {
    ...FIELD_WORDS,
    show: LABELS.form.secret.show,
    hide: LABELS.form.secret.hide,
}

/**
 * What a form drawn from a JSON Schema says beside a required field, before its issues, under a
 * field an empty box leaves to its default, and in its password boxes.
 */
export const SCHEMA_FORM_WORDS: Partial<SchemaFormWords> = {
    ...FIELD_WORDS,
    fallback: (value) => LABELS.form.default_is(typeof value === 'string' ? value : literal(value)),
    secret: SECRET_FIELD_WORDS,
}

/** What a chip's remove button is called, as a function of the chip's words: "Stop filtering by finance". */
export function chipWords(remove: (text: string) => string): ChipWords {
    return { remove, newTab: LABELS.shell.new_tab }
}

/** What a copy button is called before a press, `copy`, and for a moment after it. */
export function copyWords(copy: string): CopyButtonWords {
    return { copy, copied: LABELS.action.copy.done }
}

/** What a description's code blocks and callouts say. */
const MARKDOWN_WORDS: NonNullable<PlainMarkdownProps['words']> = {
    ...LABELS.shell.callout,
    code: copyWords(LABELS.shell.copy_code),
}

/**
 * How every description is read: its words, no image fetched, and a link live only to a web
 * address or a mailbox. Raw HTML stays off.
 */
export const DESCRIPTION_MARKDOWN = {
    words: MARKDOWN_WORDS,
    images: false,
    linkSchemes: ['https', 'http', 'mailto'],
} as const satisfies Partial<PlainMarkdownProps>

/** What a secret shown once says: its name, its copy button named for it, and that it is shown once. */
export function secretWords(noun: string): SecretRevealWords {
    return { ...copyWords(LABELS.shell.copy_secret(noun)), warning: LABELS.shell.shown_once, secret: noun }
}

/** What a search box says while it is empty, wherever one is drawn. */
export const SEARCH_PLACEHOLDER = LABELS.shell.search

/** What a search box's clear button is called. */
export const SEARCH_WORDS: SearchFieldWords = { clear: LABELS.shell.clear_search }

/** What a filter chip says: `any` heads a single choice's menu and unsets it. */
export function filterWords(any = ''): FilterChipWords {
    return {
        any,
        clear: LABELS.shell.stop_filtering,
        more: LABELS.shell.more_chosen,
        search: SEARCH_PLACEHOLDER,
        empty: LABELS.shell.no_match,
    }
}

/** A single-choice filter chip's selection, held as one value where `''` is no filter. */
export function oneChosen(value: string, onChange: (value: string) => void) {
    return {
        selected: value === '' ? [] : [value],
        onSelectedChange: (next: string[]) => {
            onChange(next[0] ?? '')
        },
    }
}

/**
 * What every listing says that is not about its rows: a refused cell's issues, and over a read that
 * failed, the heading for no answer and the button that reads again. A refusal's own heading is
 * the problem document's, given where it is drawn.
 */
export const TABLE_WORDS: Partial<DataTableWords> = {
    ...ISSUE_WORDS,
    unreachable: LABELS.refusal.no_answer.title,
    retry: LABELS.shell.read_again,
}

/**
 * How every listing's `DataTable` lays out: the list look, columns that do not drag, and its rows
 * as cards once its own box is narrower than `lg` and than the least its columns take, which
 * is never under 36rem. The next page is asked for as the rows near the end of the box.
 */
export const LISTING = {
    variant: 'list',
    words: TABLE_WORDS,
    resizable: false,
    stackBelow: '64rem',
    minWidth: '36rem',
} as const

/**
 * What a listing's bar says of its rows, in `rowsRead`'s words: "50 runs", and "50 runs, more to
 * load" while the cursor has more.
 */
export function countWords(
    noun: Counted<string>,
): Partial<DataTableWords> & Pick<DataTableWords, 'rows' | 'loaded'> {
    return {
        ...TABLE_WORDS,
        rows: (count) => rowsRead(count, noun, false),
        loaded: (count) => rowsRead(count, noun, true),
    }
}

/**
 * A listing set in a `Section` among others: unframed, and growing with its rows rather than
 * scrolling in a box of its own, so the next page is a button after the last row.
 */
export const SECTION_LISTING = {
    ...LISTING,
    framed: false,
    loadMore: 'button',
    loadMoreCount: PAGE,
    words: {
        ...TABLE_WORDS,
        loadMore: (count: number | undefined) => LABELS.shell.load_more(String(count ?? PAGE)),
    },
} as const

/** The one dismissal word a dialog's footer says. */
export const DIALOG_WORDS: Partial<DialogShellWords> = { cancel: LABELS.action.cancel }

/** What a link out of this app says to a screen reader after its text. */
export const LINK_WORDS: TextLinkWords = { newTab: LABELS.shell.new_tab }

/** What a row of tags says: a tag that narrows the listing to itself, and the `+N` that names the rest. */
export const TAG_CHIPS_WORDS: Partial<TagChipsWords> = {
    select: LABELS.shell.filter_by_tag,
    rest: (tags) => counted(tags.length, LABELS.shell.folded_tags)(String(tags.length), tags.join(', ')),
}

/** What a split button's chevron is called, "More ways to create a pipeline", and what it says on hover. */
export function splitWords(more: string, moreHint?: string): SplitButtonWords {
    return moreHint === undefined ? { more } : { more, moreHint }
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

/** What a sokkel-ui-graph canvas says: its name, its zoom buttons, and an empty canvas. */
export const GRAPH_WORDS: RunGraphProps['words'] = {
    label: LABELS.pipelines.page.graph,
    zoomIn: LABELS.shell.zoom_in,
    zoomOut: LABELS.shell.zoom_out,
    fit: LABELS.shell.fit_view,
    empty: LABELS.runs.graph_empty,
}

/** What the editor's graph says: the run graph's words, and its own empty canvas. */
export const EDITOR_GRAPH_WORDS: RunGraphProps['words'] = {
    ...GRAPH_WORDS,
    empty: LABELS.editor.canvas.no_steps,
}

/** What the editor's block picker says: its search and list, a search that finds nothing, and a catalog still being read. */
export const BLOCK_PICKER_WORDS: BlockPickerWords = {
    search: LABELS.editor.canvas.search_blocks,
    placeholder: LABELS.editor.canvas.search_blocks_placeholder,
    list: LABELS.editor.canvas.block_list,
    none: LABELS.editor.canvas.no_block_matches,
    nothing: LABELS.editor.canvas.no_block_matches,
    loading: LABELS.shell.reading,
}

/** What a sokkel-ui-graph layout menu says: its button, and the direction, edges and spacing it offers. */
export const GRAPH_LAYOUT_WORDS: Partial<GraphLayoutMenuWords> = {
    label: LABELS.shell.layout.menu,
    direction: LABELS.shell.layout.direction,
    right: LABELS.shell.layout.right,
    down: LABELS.shell.layout.down,
    routing: LABELS.shell.layout.edges,
    orthogonal: LABELS.shell.layout.orthogonal,
    splines: LABELS.shell.layout.splines,
    spacing: LABELS.shell.layout.spacing,
    compact: LABELS.shell.layout.compact,
    normal: LABELS.shell.layout.normal,
    roomy: LABELS.shell.layout.roomy,
}

/** What a diff says when nothing changed, and on the row a run of unchanged lines folds into. */
export const DIFF_WORDS: DiffViewWords = {
    unchanged: LABELS.shell.diff_unchanged,
    folded: (count) => counted(count, LABELS.shell.diff_folded)(count.toLocaleString('en')),
}

/** What a file's preview says: how many rows of a table it shows, JSON that does not parse, a kind it cannot draw, and a file cut short. */
export const FILE_PREVIEW_WORDS: FilePreviewWords = {
    rows: (shown, total) =>
        shown === total
            ? counted(total, LABELS.shell.preview_rows)(total.toLocaleString('en'))
            : LABELS.shell.preview_rows_first(shown.toLocaleString('en'), total.toLocaleString('en')),
    firstRows: (shown) => LABELS.shell.preview_rows_start(shown.toLocaleString('en')),
    unreadable: LABELS.shell.preview_unreadable,
    none: LABELS.shell.preview_none,
    cut: LABELS.shell.preview_cut,
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
    sequence: LABELS.shell.shortcuts_sequence,
    running: LABELS.palette.running,
    refused: LABELS.palette.refused,
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
