/**
 * What the new-schedule dialog decides, as functions a Node test can run.
 *
 * A DIALOG RENDERS AND THIS DECIDES. Which zones are offered and what each one's offset is,
 * whether a box of JSON is the parameters, and why Create is shut are all questions with one
 * answer, so they are answered here rather than inside a component nothing can call.
 *
 * THE FORM AND THE JSON ARE ONE VALUE. Pinned parameters are edited either as the pipeline's
 * own form or as the object that form would send, and the two are the same map read two ways:
 * `writeValues` is what the box shows and `readValues` is what typing in it means, so neither
 * view can carry a value the other does not.
 */

import type { CronFieldWords } from '@winterop-com/sokkel-ui/CronField'
import { describeCron, type CronWords } from '@winterop-com/sokkel-ui/lib/cron'

import type { JsonMap } from '@/lib/api'
import { formatMoment } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import type { RunPriority } from '@/lib/runs'

/** Which priority a trigger's runs carry, with the row that takes the pipeline's own. */
export const PRIORITIES: readonly RunPriority[] = ['low', 'normal', 'high']

/** What the row that declares no priority is called, and the token it is chosen by. */
export const INHERITED = 'inherit'

/** The pinned parameters as the box shows them: the object that would be sent, indented. */
export function writeValues(values: JsonMap): string {
    return JSON.stringify(values, null, 2)
}

/** What a box of JSON amounts to: the parameters it holds, or why it is not an object. */
export type ReadValues = { ok: true; values: JsonMap } | { ok: false; message: string }

/**
 * Read a box of JSON as the parameter map it stands for.
 *
 * AN EMPTY BOX IS AN EMPTY MAP rather than a refusal: somebody clearing the box has said the
 * trigger pins nothing, which is what the form with every field empty says as well.
 */
export function readValues(text: string): ReadValues {
    const written = text.trim()
    if (written === '') return { ok: true, values: {} }
    let value: unknown
    try {
        value = JSON.parse(written)
    } catch (error) {
        return {
            ok: false,
            message: error instanceof Error ? error.message : LABELS.triggers.dialog.params_unreadable,
        }
    }
    if (value === null || typeof value !== 'object' || Array.isArray(value)) {
        return { ok: false, message: LABELS.triggers.dialog.params_not_object }
    }
    return { ok: true, values: value as JsonMap }
}

/**
 * Every IANA zone this browser knows, which is what the timezone picker offers.
 *
 * `UTC` is always on the list: it is what a new schedule starts in when the browser's own zone
 * is unknown, and an ICU build may spell it only as `Etc/UTC`.
 */
export function zonesOffered(): string[] {
    const known = [...Intl.supportedValuesOf('timeZone')]
    return known.includes('UTC') ? known : ['UTC', ...known]
}

/** The zone this browser is in, which is what a new schedule starts in. */
export function browserZone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
}

/**
 * What a zone is at right now, as the offset it is written by: `UTC+2`.
 *
 * The offset rather than the abbreviation, because half the world's abbreviations are ambiguous
 * and an offset is the thing somebody is checking the zone for.
 */
export function zoneOffset(zone: string, at: Date = new Date()): string {
    const parts = new Intl.DateTimeFormat('en-GB', {
        timeZone: zone,
        timeZoneName: 'shortOffset',
    }).formatToParts(at)
    const named = parts.find((part) => part.type === 'timeZoneName')?.value ?? 'GMT'
    const offset = named.replace('GMT', 'UTC')
    return offset === 'UTC' ? LABELS.measure.utc_offset : offset
}

/** How many firings the instance reads back for a clock, which is how many rows the cron box draws. */
export const FIRINGS_READ = 3

/**
 * What the cron box says. Nothing is drawn beside its label: the dialog's timezone picker, above
 * the clock, is what names the zone.
 */
export const CRON_FIELD_WORDS: Partial<CronFieldWords> = {
    label: LABELS.triggers.schedule.dialog.cron_expression,
    zone: '',
    invalid: LABELS.triggers.schedule.dialog.unreadable_clock,
    invalidDetail: LABELS.triggers.schedule.dialog.cron_help,
    next: () => LABELS.triggers.schedule.dialog.next_firings,
    never: LABELS.triggers.schedule.dialog.never_fires,
    checking: LABELS.triggers.schedule.dialog.checking,
}

/**
 * What the cron box says on a saved schedule's panel: the dialog's words, and the schedule's zone
 * beside the label, since no picker above it names the zone there. A paused clock says nothing in
 * place of its runs: the chip beside the schedule's name is what says paused.
 */
export const CRON_SAVED_WORDS: Partial<CronFieldWords> = {
    label: CRON_FIELD_WORDS.label,
    next: CRON_FIELD_WORDS.next,
    never: CRON_FIELD_WORDS.never,
    checking: CRON_FIELD_WORDS.checking,
    paused: '',
}

/** One firing as every schedule clock draws it, on the wall clock of the schedule's zone. */
export function firingOf(firing: Date, zone: string): string {
    return formatMoment(firing.toISOString(), zone)
}

const READING = LABELS.triggers.schedule.reading

/**
 * The words a cron expression is read back in, in this interface's catalogue. Putting the phrases
 * together as a sentence is left to the library, which holds no words for it.
 */
const CRON_READING_WORDS: Partial<CronWords> = {
    dayNames: [
        READING.day.sunday,
        READING.day.monday,
        READING.day.tuesday,
        READING.day.wednesday,
        READING.day.thursday,
        READING.day.friday,
        READING.day.saturday,
    ],
    monthNames: [
        READING.month.january,
        READING.month.february,
        READING.month.march,
        READING.month.april,
        READING.month.may,
        READING.month.june,
        READING.month.july,
        READING.month.august,
        READING.month.september,
        READING.month.october,
        READING.month.november,
        READING.month.december,
    ],
    separator: READING.separator,
    lastSeparator: READING.last_separator,
    ordinal: READING.ordinal,
    everyMinute: READING.every_minute,
    everyMinutes: READING.every_minutes,
    everyHour: READING.every_hour,
    everyHours: READING.every_hours,
    hourly: READING.hourly,
    at: READING.at,
    minutesBetween: READING.minutes_between,
    minutesOfHours: READING.minutes_of_hours,
    daily: READING.daily,
    onDays: READING.on_days,
    weekdays: READING.weekdays,
    weekends: READING.weekends,
    lastDay: READING.last_day,
    lastWeekday: READING.last_weekday,
    nearestWeekday: READING.nearest_weekday,
    nthOf: READING.nth_of,
    lastOf: READING.last_of,
    weekdayRange: READING.weekday_range,
    onWeekdays: READING.on_weekdays,
    either: READING.either,
    inMonths: READING.in_months,
}

/** A cron expression read back in words, or null when it is not five fields the box can read. */
export function readCron(expression: string): string | null {
    return describeCron(expression, CRON_READING_WORDS)
}

/** Why Create is shut on a schedule, which is what the button carries as its title. */
export function unreadySchedule(pipeline: string, code: string, expression: string): string | undefined {
    if (pipeline === '') return LABELS.triggers.schedule.dialog.no_pipeline
    if (code.trim() === '') return LABELS.triggers.schedule.dialog.no_code
    if (expression.trim() === '') return LABELS.triggers.schedule.dialog.no_clock
    return undefined
}

/** A box that was emptied is that member left unset, not a member set to "". */
export function given(text: string): string | null {
    const trimmed = text.trim()
    return trimmed === '' ? null : trimmed
}
