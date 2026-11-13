/**
 * Every key this app answers, as the shortcuts dialog lists them.
 *
 * KEYS ARE MATCHED BY THE CHARACTER THEY PRODUCE, NOT BY THE KEY THAT PRODUCED IT, and every
 * chord sits on a letter. On a Norwegian layout the bracket, brace, pipe and backslash keys all
 * need Alt to reach at all, so a binding over one of them is a binding nobody on these machines
 * can press. A letter is a letter on every layout, and `?` is tested as the character rather
 * than as Shift plus a physical key, because which physical key makes it moves with the layout.
 *
 * The shell binds the rail's chord and the terminal's letter through sokkel-ui's `useShortcuts`,
 * which decides "not while somebody is typing" and "which modifier on which platform"; this is
 * the list the shortcuts dialog shows.
 */

import { LABELS } from '@/lib/labels'

/** The letter that hides and shows the navigation rail, under the platform's own modifier. */
export const RAIL_KEY = 'b'

/** The character that puts this list on screen. */
export const SHORTCUTS_KEY = '?'

/** The letter that shows and hides the run terminal, pressed bare. */
export const TERMINAL_KEY = 't'

/** The character that puts the caret in the screen's search box. */
export const SEARCH_KEY = '/'

/** Whether this browser runs on an Apple keyboard, which decides how a chord is spelled. */
export function applePlatform(userAgent: string): boolean {
    return /Mac|iPhone|iPad/.test(userAgent)
}

/** What the chord modifier is called here: the glyph every Apple keyboard carries, or the word. */
export function modifierLabel(apple: boolean): string {
    return apple ? '⌘' : 'Ctrl'
}

/** One shortcut: what pressing it does, and the keys pressed together to do it. */
export interface Shortcut {
    id: string
    /** What the press does, in plain language -- no key name inside the sentence. */
    action: string
    /** The keys, each spelled the way this platform spells it. */
    keys: string[]
}

/** Every shortcut this app answers, chords first because they are the ones nobody discovers. */
export function shortcuts(apple: boolean): Shortcut[] {
    const modifier = modifierLabel(apple)
    return [
        { id: 'palette', action: LABELS.shell.open_palette, keys: [modifier, 'K'] },
        { id: 'rail', action: LABELS.shell.chord.rail, keys: [modifier, 'B'] },
        { id: 'terminal', action: LABELS.shell.chord.terminal, keys: ['T'] },
        { id: 'search', action: LABELS.shell.chord.search, keys: [SEARCH_KEY] },
        { id: 'shortcuts', action: LABELS.shell.chord.shortcuts, keys: [SHORTCUTS_KEY] },
        { id: 'dismiss', action: LABELS.shell.chord.dismiss, keys: ['Esc'] },
        { id: 'choose', action: LABELS.shell.chord.choose, keys: ['Enter'] },
    ]
}
