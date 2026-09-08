/**
 * Which clock every instant in this app is read against.
 *
 * ONE STORE, CONSULTED BY THE FORMATTERS. `lib/format` is the only place an instant becomes a
 * string, and it asks here which zone to render in, so a timestamp in a table, in a panel and
 * along a log line cannot disagree about what time it is.
 *
 * LOCAL IS THE DEFAULT AND UTC IS THE CHOICE. A person reading a run at their own desk wants
 * their own clock; a person comparing this instance's log against a machine's wants the zone
 * the machine wrote in, and every instant on this API is UTC.
 */

import { createStore } from '@/lib/store'

/** Which clock instants are read against. */
export type TimesMode = 'local' | 'utc'

/** The settings, in the order the row offers them. */
export const TIMES_MODES: readonly TimesMode[] = ['local', 'utc']

/** What each setting is called on screen. */
export const TIMES_LABELS: Record<TimesMode, string> = {
    local: 'Local',
    utc: 'UTC',
}

export const DEFAULT_TIMES: TimesMode = 'local'

/** Where the choice is kept between visits. */
export const TIMES_STORAGE_KEY = 'dirigent.times'

/** Whether a string names a setting this build has. */
export function isTimesMode(candidate: string | null): candidate is TimesMode {
    return candidate !== null && (TIMES_MODES as string[]).includes(candidate)
}

/**
 * The setting this browser last chose, or the default.
 *
 * Storage that refuses to be read is the same answer as storage holding nothing: the choice
 * simply does not survive the reload.
 */
export function storedTimes(): TimesMode {
    try {
        const stored = localStorage.getItem(TIMES_STORAGE_KEY)
        return isTimesMode(stored) ? stored : DEFAULT_TIMES
    } catch {
        return DEFAULT_TIMES
    }
}

export const timesMode = createStore<TimesMode>(storedTimes())

/** Choose one setting, and keep it for the next visit. */
export function chooseTimes(mode: string): TimesMode {
    const chosen = isTimesMode(mode) ? mode : DEFAULT_TIMES
    try {
        localStorage.setItem(TIMES_STORAGE_KEY, chosen)
    } catch {
        // Storage denied: the choice holds for as long as this document is open.
    }
    timesMode.set(chosen)
    return chosen
}

/**
 * The IANA zone one setting names, or nothing for the machine's own.
 *
 * `undefined` is what `Intl` takes to mean "whatever this browser is set to", so the local
 * setting passes no zone at all rather than working out what the local one is called.
 */
export function zoneOf(mode: TimesMode): string | undefined {
    return mode === 'utc' ? 'UTC' : undefined
}

/** The zone the formatters are currently rendering in. */
export function currentZone(): string | undefined {
    return zoneOf(timesMode.get())
}

/** What a rendered instant is marked with, so a UTC reading is never mistaken for a local one. */
export function zoneSuffix(mode: TimesMode): string {
    return mode === 'utc' ? ' UTC' : ''
}

/**
 * What the clock a setting names is called, for a control that takes a wall clock.
 *
 * A `datetime-local` box carries no zone of its own, so the one it is read against has to be
 * stated beside it; a rendered instant says it in its own suffix and needs none of this.
 */
export function zoneLabel(mode: TimesMode): string {
    if (mode === 'utc') return 'UTC'
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    } catch {
        return 'UTC'
    }
}

/**
 * How far ahead of UTC the clock a setting names is, in minutes, at one instant.
 *
 * BUCKETING BY HOUR WANTS THE OFFSET, NOT THE ZONE. An hour of the clock somebody reads against
 * is an hour of UTC shifted by this, and a zone half an hour off the hour shifts it by thirty
 * minutes -- so the offset is the whole of what an hour boundary needs. It is taken at an
 * instant because a local offset moves with daylight saving.
 */
export function offsetMinutes(mode: TimesMode, at: Date): number {
    return mode === 'utc' ? 0 : -at.getTimezoneOffset()
}

/** The offset the app is reading clocks against at one instant. */
export function currentOffset(at: Date): number {
    return offsetMinutes(timesMode.get(), at)
}
