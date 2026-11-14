import { describe, expect, test } from 'vitest'

import type { IconButtonProps } from '@winterop-com/sokkel-ui/IconButton'
import { LABELS } from '@/lib/labels'
import {
    copyWords,
    countWords,
    DIALOG_WORDS,
    DIFF_WORDS,
    FIELD_WORDS,
    LINK_WORDS,
    PALETTE_SEARCH_WORDS,
    SCHEMA_CHECK_WORDS,
    SCHEMA_FORM_WORDS,
    SEARCH_PLACEHOLDER,
    SEARCH_WORDS,
    SECRET_FIELD_WORDS,
    secretWords,
    splitWords,
    TOOLBAR_WORDS,
    windowWords,
} from '@/lib/library-words'

describe('an icon button', () => {
    test('cannot be drawn without a name', () => {
        // @ts-expect-error -- an icon button without `label` is a control with no name.
        const nameless: IconButtonProps = { children: null }
        const named: IconButtonProps = { children: null, label: LABELS.action.refresh }
        expect(nameless.children).toBe(named.children)
    })
})

describe("what sokkel-ui's parts say", () => {
    test("a search box clears in the catalogue's words and says Search while empty", () => {
        expect(SEARCH_WORDS).toEqual({ clear: LABELS.shell.clear_search })
        expect(SEARCH_PLACEHOLDER).toBe(LABELS.shell.search)
    })

    test("a dialog's footer dismisses with Cancel, and its corner with Close", () => {
        expect(DIALOG_WORDS).toEqual({ cancel: LABELS.action.cancel, close: LABELS.action.close })
    })

    test('a link out of this app says it opens a new tab, and a split names its chevron', () => {
        expect(LINK_WORDS).toEqual({ newTab: LABELS.shell.new_tab })
        expect(splitWords('More ways')).toEqual({ more: 'More ways' })
        expect(splitWords('Cadence', 'How often')).toEqual({ more: 'Cadence', moreHint: 'How often' })
    })
})

describe('a verb on a strip', () => {
    test('folds into More actions, and a split names its chevron More ways', () => {
        expect(TOOLBAR_WORDS).toEqual({ more: LABELS.shell.more_actions, moreWays: LABELS.shell.more_ways })
    })
})

describe('a pane with a window', () => {
    test("names the pane on its button, and its window closes in this app's words", () => {
        expect(windowWords('report.md')).toEqual({
            expand: LABELS.shell.open_in_window('report.md'),
            close: LABELS.shell.close_window,
        })
    })

    test("an editor's schema check says deprecated beside a deprecated key", () => {
        expect(SCHEMA_CHECK_WORDS).toEqual({ deprecated: LABELS.editor.deprecated_key })
    })
})

describe('a diff', () => {
    test("says no changes and counts a folded run in this app's words", () => {
        expect(DIFF_WORDS.unchanged).toBe(LABELS.shell.diff_unchanged)
        expect(DIFF_WORDS.folded(1)).toBe(LABELS.shell.diff_folded.one('1'))
        expect(DIFF_WORDS.folded(1200)).toBe(LABELS.shell.diff_folded.many('1,200'))
    })
})

describe('a copy button', () => {
    test('is called what it copies, and says it copied after a press', () => {
        expect(copyWords('Copy the URL')).toEqual({ copy: 'Copy the URL', copied: LABELS.action.copy.done })
    })

    test('beside a secret names the secret and says it is shown once', () => {
        expect(secretWords('token')).toEqual({
            copy: LABELS.shell.copy_secret('token'),
            copied: LABELS.action.copy.done,
            warning: LABELS.shell.shown_once,
            secret: 'token',
        })
    })
})

describe("a listing bar's count", () => {
    test("says the rows in rowsRead's words", () => {
        const words = countWords(LABELS.word.run.count)
        expect(words.rows(1)).toBe('1 run')
        expect(words.rows(50)).toBe('50 runs')
        expect(words.loaded(50)).toBe('50 runs, more to load')
    })
})

describe('a form drawn from a JSON Schema', () => {
    test("marks a required field and names its issues in the catalogue's words, as every field does", () => {
        expect(SCHEMA_FORM_WORDS).toMatchObject(FIELD_WORDS)
        expect(SCHEMA_FORM_WORDS.secret).toBe(SECRET_FIELD_WORDS)
    })

    test('says the default an empty box leaves a field to, a text as it is and any other value as JSON', () => {
        expect(SCHEMA_FORM_WORDS.fallback?.('30s')).toBe(LABELS.form.default_is('30s'))
        expect(SCHEMA_FORM_WORDS.fallback?.(8)).toBe(LABELS.form.default_is('8'))
    })
})

describe("the palette's search", () => {
    test('says Reading while it reads, and asks again with Try again', () => {
        expect(PALETTE_SEARCH_WORDS.searching).toBe(LABELS.shell.reading)
        expect(PALETTE_SEARCH_WORDS.retry).toBe(LABELS.shell.read_again)
    })

    test('says why it failed when the failure has words, and that it failed when not', () => {
        expect(PALETTE_SEARCH_WORDS.failed('No run 01a1.')).toBe('No run 01a1.')
        expect(PALETTE_SEARCH_WORDS.failed(' ')).toBe(LABELS.palette.search.failed)
    })

    test('names the query on the row to every result', () => {
        expect(PALETTE_SEARCH_WORDS.seeAll('etl')).toBe(LABELS.palette.search.all_results('etl'))
    })
})
