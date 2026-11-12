import { useEffect, useState } from 'react'

import { LABELS } from '@/lib/labels'
import { refusalOf, said } from '@/lib/refusal'
import { previewSchedule } from '@/lib/triggers'

/** Which of a schedule's clock fields a clock is written in. */
export type ClockField = 'cron' | 'interval' | 'at'

/** What a clock says about itself, as the instance reads it back. */
export type Reading =
    /** Nothing has been written, or nothing is being asked, so there is nothing to read back. */
    | { kind: 'blank' }
    /** The instance has yet to answer for what is written now. */
    | { kind: 'pending' }
    /** The next firings, oldest first, in the zone the schedule declares. */
    | { kind: 'firings'; firings: string[] }
    /** What the parser made of it, in its own words. */
    | { kind: 'refused'; detail: string }

/** How long a clock is left alone before it is read back, so a keystroke is not a request. */
const PREVIEW_DELAY = 300

/**
 * What a clock would fire from now, read back from the instance's `$preview`.
 *
 * A KEYSTROKE IS NOT A REQUEST. The expression is left alone for a moment before it is asked
 * about, and an answer to a clock that has since changed is dropped rather than drawn under the
 * one now written. Nothing is asked while `asking` is false.
 */
export function useFirings(
    asking: boolean,
    clock: ClockField,
    expression: string,
    timezone: string,
): Reading {
    const written = expression.trim()
    const asked = `${clock} ${timezone} ${written}`
    const [answered, setAnswered] = useState<{ asked: string; reading: Reading } | null>(null)

    useEffect(() => {
        if (!asking || written === '') return
        let live = true
        const timer = setTimeout(() => {
            void previewSchedule({ [clock]: written, timezone }).then(
                (answer) => {
                    if (live) setAnswered({ asked, reading: { kind: 'firings', firings: answer.firings } })
                },
                (error: unknown) => {
                    const detail = said(refusalOf(error)) || LABELS.triggers.schedule.dialog.unreadable_clock
                    if (live) setAnswered({ asked, reading: { kind: 'refused', detail } })
                },
            )
        }, PREVIEW_DELAY)
        return () => {
            live = false
            clearTimeout(timer)
        }
    }, [asking, asked, clock, timezone, written])

    if (!asking || written === '') return { kind: 'blank' }
    return answered !== null && answered.asked === asked ? answered.reading : { kind: 'pending' }
}
