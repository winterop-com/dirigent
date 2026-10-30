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

import type { JsonMap } from '@/lib/api'
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
