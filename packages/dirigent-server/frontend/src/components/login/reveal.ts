/**
 * What the password field's reveal toggle is, in each of its two states.
 *
 * The control's accessible name has to say what pressing it will do while `aria-pressed` says
 * what it has already done, and the input's `type` has to agree with both. That is one decision
 * rather than three, so it is made here and asserted in Node.
 */

export const SHOW_PASSWORD_LABEL = 'Show password'
export const HIDE_PASSWORD_LABEL = 'Hide password'

export type Reveal = {
    /** What the password input's `type` is while the toggle stands this way. */
    inputType: 'password' | 'text'
    /** The toggle's accessible name: what a press would do next. */
    label: string
}

export function revealOf(shown: boolean): Reveal {
    return shown
        ? { inputType: 'text', label: HIDE_PASSWORD_LABEL }
        : { inputType: 'password', label: SHOW_PASSWORD_LABEL }
}
