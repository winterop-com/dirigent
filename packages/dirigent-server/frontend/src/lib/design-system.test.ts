import { describe, expect, test } from 'vitest'

import type { IconButtonProps } from '@winterop-com/sokkel-ui/IconButton'
import {
    copyWords,
    countWords,
    DIALOG_WORDS,
    DIFF_WORDS,
    dotOf,
    galleryAnchor,
    GALLERY_INDEX,
    isNews,
    LINK_WORDS,
    SCHEMA_CHECK_WORDS,
    saysWord,
    SEARCH_PLACEHOLDER,
    SEARCH_WORDS,
    secretWords,
    shutWith,
    splitWords,
    TOOLBAR_WORDS,
    windowWords,
} from '@/lib/design-system'
import { LABELS } from '@/lib/labels'

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

    test("a dialog's one dismissal word is Cancel", () => {
        expect(DIALOG_WORDS).toEqual({ cancel: LABELS.action.cancel })
    })

    test('a link out of this app says it opens a new tab, and a split names its chevron', () => {
        expect(LINK_WORDS).toEqual({ newTab: LABELS.shell.new_tab })
        expect(splitWords('More ways')).toEqual({ more: 'More ways' })
    })
})

describe('a verb on a strip', () => {
    test('folds into More actions, and a split names its chevron More ways', () => {
        expect(TOOLBAR_WORDS).toEqual({ more: LABELS.shell.more_actions, moreWays: LABELS.shell.more_ways })
    })

    test('is shut with its sentence where there is one, and quietly where there is none', () => {
        expect(shutWith(false, 'Viewers cannot')).toEqual({})
        expect(shutWith(true, 'Viewers cannot')).toEqual({ reason: 'Viewers cannot' })
        expect(shutWith(true, null)).toEqual({ disabled: true })
        expect(shutWith(true)).toEqual({ disabled: true })
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

describe('a dot', () => {
    test('says its word only when the state is news', () => {
        expect(saysWord(isNews({ tone: 'good' }))).toBe(false)
        expect(saysWord(isNews({ tone: 'critical' }))).toBe(true)
        expect(saysWord(isNews({ tone: 'unknown' }))).toBe(true)
        expect(saysWord(isNews({ status: 'succeeded' }))).toBe(false)
        expect(saysWord(isNews({ status: 'paused' }))).toBe(false)
        expect(saysWord(isNews({ status: 'failed' }))).toBe(true)
    })

    test('says it always or never where it is asked to', () => {
        expect(saysWord(false, 'always')).toBe(true)
        expect(saysWord(true, 'never')).toBe(false)
    })

    test('is 8px, hollow only when unknown, and says its word as a tooltip where it does not draw it', () => {
        expect(dotOf({ tone: 'good', label: 'healthy' })).toEqual({
            color: 'var(--good)',
            outline: false,
            size: 'md',
            label: 'healthy',
            say: false,
            tip: 'healthy',
            className: undefined,
        })
        expect(dotOf({ tone: 'unknown', label: 'never checked' })).toMatchObject({
            outline: true,
            say: true,
            tip: undefined,
        })
        expect(dotOf({ status: 'failed' })).toMatchObject({
            color: 'var(--status-failed)',
            label: LABELS.state.run.failed.chip,
            say: true,
        })
    })
})

describe('the gallery index', () => {
    const sections = GALLERY_INDEX.flatMap((group) => group.sections)

    test('names no section twice, so one anchor is one place', () => {
        expect(new Set(sections).size).toBe(sections.length)
        expect(new Set(sections.map(galleryAnchor)).size).toBe(sections.length)
    })

    test('says every section in a plain word the catalogue holds', () => {
        for (const section of sections) expect(LABELS.design.section[section].length).toBeGreaterThan(0)
    })

    test('says plain names, in the order the page draws them', () => {
        expect(sections.map((section) => LABELS.design.section[section])).toEqual([
            'Titles',
            'Headings',
            'Links',
            'Labels',
            'Status dots',
            'Icons',
            'Buttons',
            'Search',
            'Form fields',
            'Switches',
            'Notices',
            'Dialogs',
            'Lists of facts',
        ])
    })
})

describe("a listing bar's count", () => {
    test("says the rows in rowsRead's words, and nothing for none", () => {
        const words = countWords(LABELS.word.run.count)
        expect(words.rows(1)).toBe('1 run')
        expect(words.rows(50)).toBe('50 runs')
        expect(words.loaded(50)).toBe('50 runs, more to load')
        expect(words.rows(0)).toBe('')
    })
})
