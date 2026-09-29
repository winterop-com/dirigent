import { LABELS } from '@/lib/labels'
import { createStore } from '@/lib/store'

/**
 * How often a watched screen quietly reads itself again.
 *
 * ONE CADENCE FOR THE APP, chosen from the refresh control and kept across reloads: the
 * question "how fresh do I need this" is about the person watching, not about the screen
 * they happen to be on. `null` is off -- the manual refresh still works.
 */

/** The cadences the control offers, in seconds; null is off. */
export const REFRESH_CHOICES: readonly (number | null)[] = [null, 5, 10, 30, 60, 300]

/** What a cadence is called on the control. */
export function refreshLabel(seconds: number | null): string {
    if (seconds === null) return LABELS.shell.cadence_off
    if (seconds < 60) return LABELS.shell.cadence_seconds(String(seconds))
    return LABELS.shell.cadence_minutes(String(seconds / 60))
}

const KEY = 'dirigent.refreshSeconds'
const DEFAULT_SECONDS = 30

function readStored(): number | null {
    try {
        const stored = localStorage.getItem(KEY)
        if (stored === null) return DEFAULT_SECONDS
        if (stored === 'off') return null
        const seconds = Number(stored)
        return REFRESH_CHOICES.includes(seconds) ? seconds : DEFAULT_SECONDS
    } catch {
        return DEFAULT_SECONDS
    }
}

export const refreshSeconds = createStore<number | null>(readStored())

export function setRefreshSeconds(seconds: number | null): void {
    refreshSeconds.set(seconds)
    try {
        localStorage.setItem(KEY, seconds === null ? 'off' : String(seconds))
    } catch {
        // Storage denied: the cadence holds for as long as this document is open.
    }
}
