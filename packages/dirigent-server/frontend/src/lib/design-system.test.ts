import { describe, expect, test } from 'vitest'

import type { IconButtonProps } from '@/components/ds/IconButton'
import { clearShown, escapeFrom, iconButtonTip, isNews, saysWord } from '@/lib/design-system'
import { ICONS } from '@/lib/icons'
import { focusesSearch, type FocusedField, type KeyPress } from '@/lib/shortcuts'

function press(key: string, extra: Partial<KeyPress> = {}): KeyPress {
    return { key, ctrlKey: false, metaKey: false, altKey: false, ...extra }
}

const BODY: FocusedField = { tagName: 'BODY', isContentEditable: false }

describe("the search field's / key", () => {
    test('moves the caret into the box from the page itself', () => {
        expect(focusesSearch(press('/'), BODY)).toBe(true)
        expect(focusesSearch(press('/'), null)).toBe(true)
    })

    test('is a character, not a shortcut, while another box has focus', () => {
        expect(focusesSearch(press('/'), { tagName: 'INPUT', isContentEditable: false })).toBe(false)
        expect(focusesSearch(press('/'), { tagName: 'TEXTAREA', isContentEditable: false })).toBe(false)
        expect(focusesSearch(press('/'), { tagName: 'DIV', isContentEditable: true })).toBe(false)
    })

    test('is ignored in the editor, whose focused element need not be a field', () => {
        expect(focusesSearch(press('/'), { tagName: 'DIV', isContentEditable: false, inEditor: true })).toBe(
            false,
        )
    })

    test('is refused under a modifier, which belongs to the browser', () => {
        expect(focusesSearch(press('/', { metaKey: true }), BODY)).toBe(false)
        expect(focusesSearch(press('/', { ctrlKey: true }), BODY)).toBe(false)
        expect(focusesSearch(press('/', { altKey: true }), BODY)).toBe(false)
    })

    test('is not some other key', () => {
        expect(focusesSearch(press('?'), BODY)).toBe(false)
    })
})

describe("the search field's clear", () => {
    test('is offered only once there is text to clear', () => {
        expect(clearShown('')).toBe(false)
        expect(clearShown('ingest')).toBe(true)
        expect(clearShown(' ')).toBe(true)
    })

    test('is what Escape does to a box with text, and an empty box is left instead', () => {
        expect(escapeFrom('ingest')).toBe('clear')
        expect(escapeFrom('')).toBe('leave')
    })
})

describe("an icon button's tooltip", () => {
    test('says the name when nothing longer was given', () => {
        expect(iconButtonTip({ label: 'Refresh' })).toBe('Refresh')
    })

    test('says the longer sentence where one was given', () => {
        expect(iconButtonTip({ label: 'Fit view', tooltip: 'Fit the whole graph on screen' })).toBe(
            'Fit the whole graph on screen',
        )
    })

    test('says why a shut button is shut, ahead of anything else', () => {
        expect(iconButtonTip({ label: 'Delete', tooltip: 'Delete it', why: 'Only an admin may.' })).toBe(
            'Only an admin may.',
        )
    })

    test('cannot be drawn without a name', () => {
        // @ts-expect-error -- an icon button without `label` is a control with no name.
        const nameless: IconButtonProps = { icon: ICONS.refresh }
        const named: IconButtonProps = { icon: ICONS.refresh, label: 'Refresh' }
        expect(nameless.icon).toBe(named.icon)
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
