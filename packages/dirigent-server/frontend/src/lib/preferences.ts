/**
 * The small choices a reader makes about how this app behaves, kept between visits.
 *
 * A preference here is one that changes what a screen does rather than what it looks like: the
 * appearance axes live in `lib/theme` and sokkel-ui's appearance, and which clock an instant is
 * read against lives in `lib/times`. What is left is behaviour: how a log pane arrives, and what
 * an editor marks.
 *
 * A DEFAULT IS WHAT THIS APP DID BEFORE THE PREFERENCE EXISTED, so nothing moves under somebody
 * who has never opened the settings dialog.
 */

import { createStore } from '@winterop-com/sokkel-ui/lib/stored'

import '@/lib/stored-prefix'

/** Where the choice is kept between visits, under the app's prefix. */
export const FOLLOW_TAILS_KEY = 'followTails'

/** A log pane opens following the tail unless somebody said otherwise. */
export const DEFAULT_FOLLOW_TAILS = true

/** Where the choice is kept between visits, under the app's prefix. */
export const HIGHLIGHT_LINE_KEY = 'highlightLine'

/** An editor marks nothing under the caret unless somebody asked for it. */
export const DEFAULT_HIGHLIGHT_LINE = false

const isFlag = (value: unknown) => typeof value === 'boolean'

/**
 * Whether a log pane sticks to the newest line as it arrives.
 *
 * This is where a pane starts, not where it stays: scrolling up stops the pane following and
 * scrolling back down starts it again, because a pane that jumped to the bottom while somebody
 * was reading what failed would be unreadable during exactly the run that matters.
 */
export const followTails = createStore(DEFAULT_FOLLOW_TAILS, { key: FOLLOW_TAILS_KEY, check: isFlag })

/** Say whether log panes open following the tail. */
export function setFollowTails(following: boolean): void {
    followTails.set(following)
}

/** Whether an editor marks the row the caret is on, in place and in a window, read-only or not. */
export const highlightLine = createStore(DEFAULT_HIGHLIGHT_LINE, { key: HIGHLIGHT_LINE_KEY, check: isFlag })

/** Say whether editors mark the row the caret is on. */
export function setHighlightLine(highlighting: boolean): void {
    highlightLine.set(highlighting)
}
