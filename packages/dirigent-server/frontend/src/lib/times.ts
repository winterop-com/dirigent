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

import { LABELS } from '@/lib/labels'
import { createStore } from '@winterop-com/sokkel-ui/lib/stored'

import '@/lib/stored-prefix'

/** Which clock instants are read against. */
export type TimesMode = 'local' | 'utc'

/** The settings, in the order the row offers them. */
export const TIMES_MODES: readonly TimesMode[] = ['local', 'utc']

/** What each setting is called on screen. */
export const TIMES_LABELS: Record<TimesMode, string> = {
    local: LABELS.settings.times_local,
    utc: LABELS.measure.utc,
}

export const DEFAULT_TIMES: TimesMode = 'local'

/** Whether a string names a setting this build has. */
export function isTimesMode(candidate: unknown): candidate is TimesMode {
    return typeof candidate === 'string' && (TIMES_MODES as string[]).includes(candidate)
}

/** The setting this browser last chose, or the default; one this build does not have reads as the default. */
export const timesMode = createStore<TimesMode>(DEFAULT_TIMES, { key: 'times', check: isTimesMode })

/** Choose one setting, and keep it for the next visit. */
export function chooseTimes(mode: string): TimesMode {
    const chosen = isTimesMode(mode) ? mode : DEFAULT_TIMES
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
    return mode === 'utc' ? ` ${LABELS.measure.utc}` : ''
}

/**
 * What the clock a setting names is called, for a control that takes a wall clock.
 *
 * A `datetime-local` box carries no zone of its own, so the one it is read against has to be
 * stated beside it; a rendered instant says it in its own suffix and needs none of this.
 */
export function zoneLabel(mode: TimesMode): string {
    if (mode === 'utc') return LABELS.measure.utc
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || LABELS.measure.utc
    } catch {
        return LABELS.measure.utc
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
