/**
 * The five facts the admin dashboard opens with, composed out of listings this API already has.
 *
 * NO ENDPOINT WAS ADDED FOR THIS SCREEN. Every number below is counted here, in the browser,
 * out of pages the API already answers: the runs listing narrowed to a window, the workers
 * registry, the connections listing, and the pipelines listing. A dashboard route on the server
 * would be a second implementation of facts the listings already carry, wrong in a different
 * way from them.
 *
 * A TILE COUNTS WHAT WAS READ, AND SAYS SO. These listings page by cursor and answer no total,
 * so a page whose `next` is not null has been truncated -- and the tile states `50+` rather
 * than 50, because claiming a total nobody counted is the one thing a dashboard must not do.
 *
 * THE COMPOSERS ARE PURE: pages in, tile facts out. What a tile says about a fleet with one
 * quiet worker and one draining one is therefore a decision a Node test makes.
 */

import type { Page } from '@/lib/api'
import { connectionsHealth, healthOf, type ConnectionOut } from '@/lib/connections'
import { titleOf } from '@/lib/identity'
import type { PipelineOut } from '@/lib/pipelines'
import type { RunOut } from '@/lib/runs'
import type { RunStatus } from '@/lib/status'
import { concernNote, workerAlive, worstConcern, type Concern, type WorkerOut } from '@/lib/workers'

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

/** How far back the first tile looks, as this API's `since` spells a window. */
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

/** A count, marked when the page it was counted off was not the whole listing. */
export function atLeast(count: number, truncated: boolean): string {
    return `${String(count)}${truncated ? '+' : ''}`
}

/** A count of rows read, marked when the page it was counted from was not the whole listing. */
export function counted(page: Page<unknown>): string {
    return atLeast(page.items.length, page.next !== null)
}

/** How many runs of the page are in each state. */
export function bucketByStatus(runs: readonly RunOut[]): Record<string, number> {
    const buckets: Record<string, number> = {}
    for (const run of runs) buckets[run.status] = (buckets[run.status] ?? 0) + 1
    return buckets
}

/**
 * The states that actually occurred, as one sentence, or nothing when none of them did.
 *
 * A state nothing is in is left out rather than counted at zero: "3 failed, 0 finished with
 * errors" spends a clause saying nothing happened, and a reader has to read it to find that out.
 * Nothing at all in any of them is not a sentence, so the caller says what an empty set means.
 */
export function summarise(counts: readonly (readonly [number, string])[]): string | null {
    const said = counts.filter(([count]) => count > 0).map(([count, noun]) => `${String(count)} ${noun}`)
    return said.length === 0 ? null : `${said.join(', ')}.`
}

/**
 * The states a run stops in, and the noun each is counted in.
 *
 * The order is the order the sentence reads them in, worst last, so the clause a reader is
 * looking for is the one nearest the full stop.
 */
const SETTLED: readonly (readonly [RunStatus, string])[] = [
    ['succeeded', 'succeeded'],
    ['cancelled', 'cancelled'],
    ['completed_with_errors', 'finished with errors'],
    ['failed', 'failed'],
]

/**
 * What the last day of runs came to, counted by the state each of them settled in.
 *
 * A RUN STILL GOING IS NOT COUNTED HERE. It is in the window and it is in the number above the
 * sentence, but it has settled in no state, so the sentence has no clause to spend on it -- what
 * is running is the question "right now" answers.
 */
export function dayTile(runs: Page<RunOut>): Tile {
    const buckets = bucketByStatus(runs.items)
    const count = (status: RunStatus) => buckets[status] ?? 0
    const settled = summarise(SETTLED.map(([status, noun]) => [count(status), noun] as const))
    const note =
        runs.items.length === 0
            ? 'Nothing has run in the last day.'
            : (settled ?? 'Nothing has finished.')
    const tone: TileTone =
        runs.items.length === 0
            ? 'neutral'
            : count('failed') > 0
              ? 'critical'
              : count('completed_with_errors') > 0
                ? 'warning'
                : count('succeeded') > 0
                  ? 'good'
                  : 'neutral'
    return { id: 'day', label: 'Last 24 hours', value: counted(runs), note, tone, to: '/runs' }
}

/** What this instance is doing at this moment, out of the same page. */
export function nowTile(runs: Page<RunOut>): Tile {
    const buckets = bucketByStatus(runs.items)
    const running = buckets.running ?? 0
    const queued = buckets.queued ?? 0
    const note =
        summarise([
            [running, 'running'],
            [queued, 'waiting to be claimed'],
        ]) ?? 'Nothing is running and nothing is waiting.'
    return {
        id: 'now',
        label: 'Right now',
        value: String(running + queued),
        note,
        tone: running + queued === 0 ? 'neutral' : 'info',
        to: '/runs',
    }
}

/** How loudly one worker's concern is drawn. */
export function concernTone(concern: Concern): TileTone {
    if (concern === 'silent' || concern === 'mismatched') return 'critical'
    if (concern === 'draining' || concern === 'stopped') return 'warning'
    return 'neutral'
}

/**
 * How much of the fleet is answering, and the worst thing any of it has to say.
 *
 * The subline is the worst fact rather than a summary, because a summary of a fleet is a number
 * somebody then has to go and look up anyway.
 */
export function workersTile(workers: Page<WorkerOut>): Tile {
    const alive = workers.items.filter(workerAlive).length
    const worst = worstConcern(workers.items)
    if (workers.items.length === 0) {
        return {
            id: 'workers',
            label: 'Workers',
            value: '0',
            note: 'No worker has registered with this instance.',
            tone: 'warning',
            to: '/admin/workers',
        }
    }
    return {
        id: 'workers',
        label: 'Workers',
        value: `${String(alive)} of ${counted(workers)}`,
        note: worst === null ? 'Every worker is answering.' : `${concernNote(worst.worker, worst.concern)}.`,
        tone: worst === null ? 'good' : concernTone(worst.concern),
        to: '/admin/workers',
    }
}

/**
 * How many connections answered the last time anything asked, and which one did not.
 *
 * COUNTED WHERE EVERY SCREEN COUNTS IT. `connectionsHealth` is what the dashboard's health foot
 * and the connections screen's own bar read, so a credential nothing has checked reads the same
 * here as it does there.
 */
export function connectionsTile(connections: Page<ConnectionOut>): Tile {
    const rows = connections.items
    const { healthy, unchecked } = connectionsHealth(rows)
    const failing = rows.find((row) => healthOf(row).state === 'failed') ?? null
    if (rows.length === 0) {
        return {
            id: 'connections',
            label: 'Connections',
            value: '0',
            note: 'This instance holds no connections.',
            tone: 'neutral',
            to: '/connections',
        }
    }
    const note =
        failing !== null
            ? `${titleOf(failing)} did not answer${failing.last_check_detail === null ? '' : `: ${failing.last_check_detail}`}`
            : unchecked > 0
              ? `${String(unchecked)} ${unchecked === 1 ? 'has' : 'have'} never been checked.`
              : 'Every connection answered when it was last checked.'
    return {
        id: 'connections',
        label: 'Connections',
        value: `${String(healthy)} of ${counted(connections)}`,
        note,
        tone: failing !== null ? 'critical' : unchecked > 0 ? 'neutral' : 'good',
        to: '/connections',
    }
}

/**
 * How much of this instance fires on its own.
 *
 * COUNTED OFF THE PIPELINES LISTING, because a schedule belongs to a pipeline and this API has
 * no listing of every schedule on the instance. `PipelineOut.schedules` is counted by the same
 * query that reads the page, so this is one request; the soonest `next_fire_at` would be one
 * request per pipeline, which is not a fact a dashboard may spend a fan-out on.
 *
 * EVERY NUMBER HERE IS COUNTED OFF THE SAME PAGE, so a page the cursor says was cut short makes
 * all three a floor rather than a count, and all three wear the mark that says so.
 */
export function schedulesTile(pipelines: Page<PipelineOut>): Tile {
    const truncated = pipelines.next !== null
    const scheduled = pipelines.items.filter((row) => row.schedules > 0)
    const schedules = scheduled.reduce((sum, row) => sum + row.schedules, 0)
    return {
        id: 'schedules',
        label: 'Schedules',
        value: atLeast(schedules, truncated),
        note:
            schedules === 0
                ? 'Nothing on this instance fires on its own.'
                : `Across ${atLeast(scheduled.length, truncated)} of ${counted(pipelines)} pipelines.`,
        tone: 'neutral',
        to: '/triggers',
    }
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
    }))
}
