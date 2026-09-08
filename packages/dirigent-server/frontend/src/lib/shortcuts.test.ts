import { describe, expect, test } from 'vitest'

import {
    applePlatform,
    isTypingField,
    opensPalette,
    opensShortcuts,
    shortcuts,
    togglesRail,
    togglesTerminal,
} from '@/lib/shortcuts'

function press(key: string, modifiers: Partial<{ ctrlKey: boolean; metaKey: boolean; altKey: boolean }> = {}) {
    return { key, ctrlKey: false, metaKey: false, altKey: false, ...modifiers }
}

const TEXT_BOX = { tagName: 'INPUT', isContentEditable: false }
const PROSE = { tagName: 'DIV', isContentEditable: true }

describe('the palette chord', () => {
    test('answers either modifier, because both mean the palette everywhere it exists', () => {
        expect(opensPalette(press('k', { metaKey: true }))).toBe(true)
        expect(opensPalette(press('k', { ctrlKey: true }))).toBe(true)
    })

    test('is a letter, matched by the character the press produced', () => {
        expect(opensPalette(press('K', { metaKey: true }))).toBe(true)
    })

    test('needs a modifier, so typing k into a box is typing', () => {
        expect(opensPalette(press('k'))).toBe(false)
    })

    test('refuses Alt, which a Nordic layout needs for other characters entirely', () => {
        expect(opensPalette(press('k', { metaKey: true, altKey: true }))).toBe(false)
    })
})

describe('the rail chord', () => {
    test('is Cmd on an Apple keyboard and Ctrl everywhere else', () => {
        expect(togglesRail(press('b', { metaKey: true }), null, true)).toBe(true)
        expect(togglesRail(press('b', { ctrlKey: true }), null, false)).toBe(true)
    })

    test('leaves Ctrl+B alone on macOS, where every text field answers it', () => {
        expect(togglesRail(press('b', { ctrlKey: true }), null, true)).toBe(false)
    })

    test('fires while a box has focus, because that is when clearing the screen is worth most', () => {
        expect(togglesRail(press('b', { metaKey: true }), TEXT_BOX, true)).toBe(true)
    })

    test('leaves a rich-text region alone, where the chord has meant bold for forty years', () => {
        expect(togglesRail(press('b', { metaKey: true }), PROSE, true)).toBe(false)
    })
})

describe('the shortcuts key', () => {
    test('is the character, whatever the layout pressed to make it', () => {
        expect(opensShortcuts(press('?'), null)).toBe(true)
    })

    test('never interrupts something being typed into', () => {
        expect(opensShortcuts(press('?'), TEXT_BOX)).toBe(false)
        expect(opensShortcuts(press('?'), PROSE)).toBe(false)
    })

    test('refuses every chord modifier, each of which means something else somewhere', () => {
        expect(opensShortcuts(press('?', { metaKey: true }), null)).toBe(false)
        expect(opensShortcuts(press('?', { altKey: true }), null)).toBe(false)
    })
})

describe('the terminal key', () => {
    test('is a bare letter, matched by the character the press produced', () => {
        expect(togglesTerminal(press('t'), null)).toBe(true)
        expect(togglesTerminal(press('T'), null)).toBe(true)
    })

    test('never interrupts something being typed into', () => {
        // The drawer has a match box of its own, and a `t` typed into it is a letter.
        expect(togglesTerminal(press('t'), TEXT_BOX)).toBe(false)
        expect(togglesTerminal(press('t'), PROSE)).toBe(false)
    })

    test('refuses every modifier, each of which is somebody else\'s binding', () => {
        expect(togglesTerminal(press('t', { metaKey: true }), null)).toBe(false)
        expect(togglesTerminal(press('t', { ctrlKey: true }), null)).toBe(false)
        expect(togglesTerminal(press('t', { altKey: true }), null)).toBe(false)
    })

    test('is claimed by nothing else this app binds', () => {
        expect(opensPalette(press('t'))).toBe(false)
        expect(togglesRail(press('t'), null, true)).toBe(false)
        expect(opensShortcuts(press('t'), null)).toBe(false)
    })
})

describe('the list of shortcuts', () => {
    test('binds letters and nothing else, because a bracket needs Alt on a Nordic layout', () => {
        const bound = shortcuts(true).flatMap((row) => row.keys)
        expect(bound.filter((key) => /^[[\]{}|\\]$/.test(key))).toEqual([])
    })

    test('spells the modifier the way the platform spells it', () => {
        expect(shortcuts(true)[0].keys[0]).toBe('⌘')
        expect(shortcuts(false)[0].keys[0]).toBe('Ctrl')
    })
})

describe('what counts as typing', () => {
    test('is a field, a text area, a select, or a rich-text region', () => {
        expect(isTypingField(TEXT_BOX)).toBe(true)
        expect(isTypingField({ tagName: 'TEXTAREA', isContentEditable: false })).toBe(true)
        expect(isTypingField(PROSE)).toBe(true)
        expect(isTypingField({ tagName: 'BUTTON', isContentEditable: false })).toBe(false)
        expect(isTypingField(null)).toBe(false)
    })
})

describe('the platform', () => {
    test('is read off the user agent, which is what decides how a chord is spelled', () => {
        expect(applePlatform('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)')).toBe(true)
        expect(applePlatform('Mozilla/5.0 (X11; Linux x86_64)')).toBe(false)
    })
})
