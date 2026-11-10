import { describe, expect, test } from 'vitest'

import type { IconButtonProps } from '@winterop-com/sokkel-ui/IconButton'
import {
    copyWords,
    DIALOG_WORDS,
    galleryAnchor,
    GALLERY_INDEX,
    isNews,
    LINK_WORDS,
    saysWord,
    SEARCH_PLACEHOLDER,
    SEARCH_WORDS,
    secretWords,
    splitWords,
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
