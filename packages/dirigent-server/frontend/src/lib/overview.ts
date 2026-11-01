/**
 * The tile shape and the runs that want somebody, which the dashboard reads.
 */

import type { RunOut } from '@/lib/runs'
import type { PipelineOut, StepShape } from '@/lib/pipelines'
import type { Concern } from '@/lib/workers'

/** How loudly a tile is drawn. The four semantic aliases, plus the absence of any of them. */
export type TileTone = 'neutral' | 'good' | 'info' | 'warning' | 'critical'

/** One tile: a number, the sentence under it, and the screen that explains it. */
export interface Tile {
    id: string
    label: string
    /** The number, already read as a string, because a truncated page reads `50+`. */
    value: string
    /** The one line under the number. */
    note: string
    tone: TileTone
    /** The screen this tile links to, which is the screen that explains the number. */
    to: string
}

/** How far back the dashboard looks, as this API's `since` spells a window. */
export const DAY = '24h'

/**
 * How many rows a tile's read asks for. Larger than a table's page: a count wants the rows.
 *
 * This is `MAX_PAGE` on the server and a 422 above it, so it is as much of a window as one
 * request can hold -- which is what a count and the chart drawn beside it read, once, together.
 */
export const TILE_PAGE = 500

/** How many rows the "needs a look" feed shows. */
export const LOOK_ROWS = 6

/** How loudly one worker's concern is drawn. */
export function concernTone(concern: Concern): TileTone {
    if (concern === 'silent' || concern === 'mismatched') return 'critical'
    if (concern === 'draining' || concern === 'stopped') return 'warning'
    return 'neutral'
}

/**
 * The runs that want somebody, newest first.
 *
 * TWO LISTING CALLS AND NO MORE. `GET /runs` narrows to one status at a time, so the two states
 * that mean "go and look" are two reads, merged here. Sorted by when each was created, because
 * a run that has not started has no `started_at` to sort on.
 */
export function needsALook(
    failed: readonly RunOut[],
    withErrors: readonly RunOut[],
    rows: number = LOOK_ROWS,
): RunOut[] {
    return [...failed, ...withErrors]
        .toSorted((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
        .slice(0, rows)
}

/** One run that wants somebody, headed the way every screen heads a pipeline. */
export interface LookEntry {
    run: RunOut
    /** What the pipeline is called, or null when it has no name or none has been read. */
    name: string | null
    /** The step the run died in, which the run's own row names. */
    failedStep: string | null
    /** The pipeline's current shape, which the row's miniature draws. */
    shape: StepShape[]
}

/**
 * The runs that want somebody, joined to what their pipelines are called.
 *
 * A RUN CARRIES A CODE AND NOTHING ELSE, so the title comes from the pipelines listing this
 * screen has already read rather than from a read per row. A code that listing did not reach is
 * still headed by its code, which is what `titleOf` answers for a pipeline with no name anyway.
 */
export function withPipelines(runs: readonly RunOut[], pipelines: readonly PipelineOut[]): LookEntry[] {
    const held = new Map(pipelines.map((row) => [row.code, row]))
    return runs.map((run) => ({
        run,
        name: held.get(run.pipeline)?.name ?? null,
        failedStep: run.failed_step,
        shape: held.get(run.pipeline)?.shape ?? [],
    }))
}
