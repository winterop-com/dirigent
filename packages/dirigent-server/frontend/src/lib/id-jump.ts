/**
 * An id pasted into the palette, opened as the run it names.
 *
 * An engine log line names an attempt by its id, and a run is named the same way. Either one,
 * pasted whole, is one row in the palette: an attempt opens its run with its step chosen and
 * that try marked, and an id no attempt holds opens as a run, whose screen says so when no run
 * holds it either.
 */

import { ApiError } from '@/lib/api'
import { readAttempt, type AttemptDetail } from '@/lib/runs'
import { ATTEMPT_PARAM, runStepPath } from '@/lib/step-address'

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

/** The id a query is, lowercased, or null when it is anything else. */
export function idOf(query: string): string | null {
    const trimmed = query.trim()
    return UUID.test(trimmed) ? trimmed.toLowerCase() : null
}

/** The address of a run with an attempt's step chosen and that try marked. */
export function attemptPath(attempt: Pick<AttemptDetail, 'id' | 'run_id' | 'step_name'>): string {
    return `${runStepPath(attempt.run_id, attempt.step_name)}?${ATTEMPT_PARAM}=${encodeURIComponent(attempt.id)}`
}

/** Where an id opens: its attempt's run when it is an attempt's, and the run it names otherwise. */
export async function addressOfId(
    id: string,
    read: (id: string) => Promise<AttemptDetail> = readAttempt,
): Promise<string> {
    try {
        return attemptPath(await read(id))
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) return runStepPath(id, null)
        throw error
    }
}
