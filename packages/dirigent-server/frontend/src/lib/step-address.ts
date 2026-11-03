/**
 * A chosen step is an address.
 *
 * `/runs/<run id>/<step code>` is a run with that step chosen and its panel open, and
 * `/pipelines/<code>/<step code>` is a pipeline's page with that step chosen. Under a run's step, a
 * fan-out's element and one try ride in the query as `item` and `attempt`. Every other query
 * parameter the address carried -- a run's `tab` -- is kept as it was.
 */

/** The query parameters naming a fan-out element and a try of a run's chosen step. */
export const ITEM_PARAM = 'item'
export const ATTEMPT_PARAM = 'attempt'

/** The address of a run, with a step chosen or none. */
export function runStepPath(run: string, step: string | null): string {
    const base = `/runs/${encodeURIComponent(run)}`
    return step === null ? base : `${base}/${encodeURIComponent(step)}`
}

/** The address of a pipeline's page, with a step chosen or none. */
export function pipelineStepPath(pipeline: string, step: string | null): string {
    const base = `/pipelines/${encodeURIComponent(pipeline)}`
    return step === null ? base : `${base}/${encodeURIComponent(step)}`
}

/**
 * The query an address keeps when the chosen step changes: everything it had, less an element
 * or a try, which belong to the step that was chosen before.
 */
export function queryForStep(query: string): string {
    const kept = new URLSearchParams(query)
    kept.delete(ITEM_PARAM)
    kept.delete(ATTEMPT_PARAM)
    const said = kept.toString()
    return said === '' ? '' : `?${said}`
}

/** The query with an element or a try of the chosen step named, or no longer named. */
export function queryWith(query: string, name: string, value: string | null): string {
    const next = new URLSearchParams(query)
    if (value === null) next.delete(name)
    else next.set(name, value)
    const said = next.toString()
    return said === '' ? '' : `?${said}`
}

/** What an address naming a step resolves to against the steps a graph holds. */
export type ChosenStep = { kind: 'none' } | { kind: 'step'; code: string } | { kind: 'unknown'; code: string }

/**
 * Which step an address chooses: none, one the graph holds, or a code it does not hold -- which
 * opens the screen with nothing chosen and a line saying so. While the graph is still being read,
 * nothing is chosen and nothing is called unknown.
 */
export function chosenStep(code: string | undefined, steps: readonly string[] | null): ChosenStep {
    if (code === undefined || code === '' || steps === null) return { kind: 'none' }
    return steps.includes(code) ? { kind: 'step', code } : { kind: 'unknown', code }
}
