/**
 * The small choices a reader makes about how this app behaves, kept between visits.
 *
 * A preference here is one that changes what a screen does rather than what it looks like: the
 * appearance axes live in `lib/theme` and next-themes, and which clock an instant is read
 * against lives in `lib/times`. What is left is behaviour, and today that is one thing.
 */

import { createStore } from '@/lib/store'

/** Where the choice is kept between visits. */
export const FOLLOW_TAILS_KEY = 'dirigent.followTails'

/** A log pane opens following the tail unless somebody said otherwise. */
export const DEFAULT_FOLLOW_TAILS = true

function readFlag(key: string, fallback: boolean): boolean {
    try {
        const stored = localStorage.getItem(key)
        return stored === null ? fallback : stored === 'true'
    } catch {
        return fallback
    }
}

/**
 * Whether a log pane sticks to the newest line as it arrives.
 *
 * This is where a pane starts, not where it stays: scrolling up stops the pane following and
 * scrolling back down starts it again, because a pane that jumped to the bottom while somebody
 * was reading what failed would be unreadable during exactly the run that matters.
 */
export const followTails = createStore(readFlag(FOLLOW_TAILS_KEY, DEFAULT_FOLLOW_TAILS))

/** Say whether log panes open following the tail. */
export function setFollowTails(following: boolean): void {
    try {
        localStorage.setItem(FOLLOW_TAILS_KEY, String(following))
    } catch {
        // Storage denied: the choice holds for as long as this document is open.
    }
    followTails.set(following)
}
