/**
 * Every key this app answers, and the rules that decide when a press is one of them.
 *
 * KEYS ARE MATCHED BY THE CHARACTER THEY PRODUCE, NOT BY THE KEY THAT PRODUCED IT, and every
 * chord sits on a letter. On a Norwegian layout the bracket, brace, pipe and backslash keys all
 * need Alt to reach at all, so a binding over one of them is a binding nobody on these machines
 * can press. A letter is a letter on every layout, and `?` is tested as the character rather
 * than as Shift plus a physical key, because which physical key makes it moves with the layout.
 *
 * THE PRESS IS DECIDED HERE AND READ ELSEWHERE. These take a plain description of the press and
 * of whatever has focus, so the awkward half of a shortcut -- "not while somebody is typing",
 * "which modifier on which platform" -- is a pure function with a test rather than a condition
 * buried in an effect.
 */

/** The letter that opens the command palette, under either modifier. */
export const PALETTE_KEY = 'k'

/** The letter that collapses and expands the navigation rail, under the platform's own modifier. */
export const RAIL_KEY = 'b'

/** The character that puts this list on screen. */
export const SHORTCUTS_KEY = '?'

/** The letter that shows and hides the run terminal, pressed bare. */
export const TERMINAL_KEY = 't'

/** The tags a person types into. A press that lands in one of these is typing, not a shortcut. */
export const TYPING_TAG_NAMES = ['INPUT', 'TEXTAREA', 'SELECT']

/** One key press, reduced to what a shortcut has to know about it. */
export interface KeyPress {
    /** The character or named key the press produced -- `event.key`, verbatim. */
    key: string
    ctrlKey: boolean
    metaKey: boolean
    altKey: boolean
}

/** Whatever has focus, reduced to what a shortcut has to know about it. */
export interface FocusedField {
    /** The element's tag, upper case as the DOM gives it. */
    tagName: string
    /** True inside a rich-text region, where the browser claims plain letters. */
    isContentEditable: boolean
}

/** Whether something is being typed into, which a bare-character shortcut must never interrupt. */
export function isTypingField(focused: FocusedField | null): boolean {
    if (focused === null) return false
    return TYPING_TAG_NAMES.includes(focused.tagName.toUpperCase()) || focused.isContentEditable
}

/**
 * Whether this press opens the command palette.
 *
 * Either modifier, unlike the rail: Cmd+K and Ctrl+K both mean the palette in every app that
 * has one, and neither is claimed by anything here. It fires while a box has focus, because
 * the palette is how somebody leaves the box they are in.
 */
export function opensPalette(press: KeyPress): boolean {
    if (press.key.toLowerCase() !== PALETTE_KEY) return false
    if (press.altKey) return false
    return press.metaKey || press.ctrlKey
}

/**
 * Whether this press collapses or expands the navigation rail.
 *
 * CMD ON APPLE KEYBOARDS AND CTRL EVERYWHERE ELSE, rather than either modifier. Ctrl+B on macOS
 * is the emacs-style "back one character" that every text field answers, and a binding that
 * swallowed it would take a caret movement away from every input in the app.
 */
export function togglesRail(press: KeyPress, focused: FocusedField | null, apple: boolean): boolean {
    if (press.key.toLowerCase() !== RAIL_KEY) return false
    if (press.altKey) return false
    if (apple ? !press.metaKey : !press.ctrlKey || press.metaKey) return false
    return !(focused?.isContentEditable ?? false)
}

/**
 * Whether this press asks for the list of shortcuts.
 *
 * No modifier beyond whatever the layout needs to produce the character: Shift is how most
 * keyboards make a `?` and so is not a modifier this can refuse, while Ctrl, Cmd and Alt each
 * mean something else somewhere. Never while something is being typed into -- a `?` typed into
 * a filter box is a question mark and nothing else.
 */
export function opensShortcuts(press: KeyPress, focused: FocusedField | null): boolean {
    if (press.key !== SHORTCUTS_KEY) return false
    if (press.ctrlKey || press.metaKey || press.altKey) return false
    return !isTypingField(focused)
}

/**
 * Whether this press shows or hides the run terminal.
 *
 * A BARE LETTER, AND NO MODIFIER AT ALL. Every chord this app has is already spoken for, and
 * `t` is not: a modifier over it would be a third thing to remember for a drawer somebody opens
 * and closes while reading. Never while something is being typed into -- a `t` typed into the
 * drawer's own match box is a letter -- and never under a modifier, where it is the browser's
 * new tab and not this app's to take.
 */
export function togglesTerminal(press: KeyPress, focused: FocusedField | null): boolean {
    if (press.key.toLowerCase() !== TERMINAL_KEY) return false
    if (press.ctrlKey || press.metaKey || press.altKey) return false
    return !isTypingField(focused)
}

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
        { id: 'palette', action: 'Open the command palette', keys: [modifier, 'K'] },
        { id: 'rail', action: 'Collapse or expand the navigation', keys: [modifier, 'B'] },
        { id: 'terminal', action: "Show or hide a run's terminal", keys: ['T'] },
        { id: 'shortcuts', action: 'Open this list', keys: [SHORTCUTS_KEY] },
        { id: 'dismiss', action: 'Close a dialog, a menu, or the palette', keys: ['Esc'] },
        { id: 'choose', action: 'Open the row that has focus', keys: ['Enter'] },
    ]
}
