import { LABELS } from '@/lib/labels'
import { createStore } from '@winterop-com/sokkel-ui/lib/stored'

import '@/lib/stored-prefix'

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

const DEFAULT_SECONDS = 30

/** The cadence kept between visits; one the control no longer offers reads as the default. */
export const refreshSeconds = createStore<number | null>(DEFAULT_SECONDS, {
    key: 'refreshSeconds',
    check: (value) => REFRESH_CHOICES.includes(value as number | null),
})

export function setRefreshSeconds(seconds: number | null): void {
    refreshSeconds.set(seconds)
}
