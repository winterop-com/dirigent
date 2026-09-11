/**
 * The front door, composed out of the listings every account can already read.
 *
 * NOTHING HERE IS ADMIN'S. Every read this screen makes is one the server answers for any
 * principal -- the runs listing, the pipelines listing, a pipeline's own schedules, the worker
 * registry and the connections listing. The admin overview asks the same questions and more
 * that need the role, and the tiles and rows the two screens share are `lib/overview`'s rather
 * than copied into this file.
 *
 * THE COMPOSERS ARE PURE: pages in, rows out. What a paused schedule does to the next firings,
 * and what order a live run is listed in, are decisions a Node test makes.
 */

import type { Page } from '@/lib/api'
import { connectionsHealth, connectionsNote, type ConnectionOut } from '@/lib/connections'
import { concernTone, DAY, type Tile, type TileTone } from '@/lib/overview'
import { readPipelines, type PipelineOut } from '@/lib/pipelines'
import { EVERY_RUN, runsLink, type RunOut } from '@/lib/runs'
import type { RunStatus } from '@/lib/status'
import { nextFireView, readSchedules, type ScheduleOut } from '@/lib/triggers'
import { concernOf, concernSaid, type WorkerOut } from '@/lib/workers'

/** How many live runs the screen lists before it stops and points at the listing. */
export const LIVE_ROWS = 6

/**
 * A count of some of a page's rows, marked when the page was not the whole listing.
 *
 * `counted` in `lib/overview` says this of a whole page; this says it of a subset, and the mark
 * is the same one for the same reason -- a truncated page can only ever put a floor under a
 * count, and a number that claimed to be a total nobody counted is the one thing a tile may not
 * do.
 */
export function partOf(count: number, page: Page<unknown>): string {
    return `${String(count)}${page.next === null ? '' : '+'}`
}

/**
 * How loudly a count is drawn.
 *
 * NOTHING AT ZERO IS LOUD. A tile is a fixed slot, so a state nothing is in still holds its
 * place -- but a zero drawn in the colour of the thing it is counting says an instance has
 * failures when what it has is none. One rule for every tile rather than a rule per tile.
 */
export function toneOf(count: number, tone: TileTone): TileTone {
    return count === 0 ? 'neutral' : tone
}

/** One tile slot, held by what it counts rather than by where it sits in the row. */
export interface TileSlot {
    id: string
    /** The tile, or null while the read behind it has not landed. */
    tile: Tile | null
}

/** How many of a page's rows settled in one state. */
function inState(page: Page<RunOut>, status: RunStatus): number {
    return page.items.filter((run) => run.status === status).length
}

/**
 * The six numbers the screen opens with: the last day by outcome, and what is going right now.
 *
 * EACH TILE LINKS TO THE ROWS IT COUNTED, window and all. The first four are counted out of one
 * windowed read, so they carry that window into the listing they open; running and queued are
 * counted out of unwindowed reads, because a run that has been going since before the window is
 * exactly the run somebody opening this screen most wants to see, and their links say the same.
 *
 * A SLOT WHOSE READ HAS NOT LANDED IS NULL rather than a zero, so the row holds its shape
 * without stating a count nobody has made yet.
 */
export function statTiles(
    day: Page<RunOut> | null,
    running: Page<RunOut> | null,
    queued: Page<RunOut> | null,
): TileSlot[] {
    const windowed = (status: RunStatus, label: string, tone: TileTone): Tile | null => {
        if (day === null) return null
        const count = inState(day, status)
        return {
            id: status,
            label,
            value: partOf(count, day),
            note: '',
            tone: toneOf(count, tone),
            to: runsLink({ ...EVERY_RUN, status, since: DAY }),
        }
    }
    const live = (
        status: RunStatus,
        label: string,
        tone: TileTone,
        note: string,
        page: Page<RunOut> | null,
    ) => {
        if (page === null) return null
        const count = page.items.length
        return {
            id: status,
            label,
            value: partOf(count, page),
            note: count === 0 ? '' : note,
            tone: toneOf(count, tone),
            to: runsLink({ ...EVERY_RUN, status }),
        }
    }
    return [
        {
            id: 'runs',
            tile:
                day === null
                    ? null
                    : {
                          id: 'runs',
                          label: 'Runs',
                          value: partOf(day.items.length, day),
                          note: 'Last 24 hours.',
                          tone: 'neutral',
                          to: runsLink({ ...EVERY_RUN, since: DAY }),
                      },
        },
        { id: 'succeeded', tile: windowed('succeeded', 'Succeeded', 'good') },
        { id: 'failed', tile: windowed('failed', 'Failed', 'critical') },
        { id: 'completed_with_errors', tile: windowed('completed_with_errors', 'With errors', 'warning') },
        { id: 'running', tile: live('running', 'Running', 'info', 'Being worked on now.', running) },
        { id: 'queued', tile: live('queued', 'Queued', 'neutral', 'Waiting for a worker.', queued) },
    ]
}

/** How many hours of runs the chart draws. */
export const CHART_HOURS = 24

const HOUR_MS = 3_600_000

const DAY_MS = 86_400_000

/** One hour of the chart: when it began, and how the runs created in it came out. */
export interface HourBucket {
    /** The instant the hour starts, in milliseconds since the epoch. */
    start: number
    /** Which hour of the clock it is read against, 0 to 23. */
    hour: number
    succeeded: number
    withErrors: number
    failed: number
    /** Every run created in the hour, including the ones that have not settled. */
    total: number
}

/** The start of the hour an instant falls in, on a clock this many minutes ahead of UTC. */
export function hourStart(at: number, offset: number): number {
    const shifted = at + offset * 60_000
    return Math.floor(shifted / HOUR_MS) * HOUR_MS - offset * 60_000
}

/** Which hour of that clock an instant falls in. */
export function hourOf(at: number, offset: number): number {
    const shifted = at + offset * 60_000
    return Math.floor((((shifted % DAY_MS) + DAY_MS) % DAY_MS) / HOUR_MS)
}

/**
 * The last 24 hours of runs, counted into the hour each was created in.
 *
 * THE CLOCK IS THE READER'S. A bar is read against the hour somebody was working in, so the
 * boundaries are the hours of the zone `lib/times` is set to -- passed in as an offset, which
 * is the whole of what an hour boundary needs and is what makes this pure.
 *
 * IT COUNTS WHAT IT WAS GIVEN. `since` narrows the runs listing by `created_at`, so that is
 * what a run is bucketed by; an hour nothing ran in is a bucket at zero rather than a gap, or
 * the axis would say a different day had passed than the one it drew.
 */
export function hourlyRuns(
    runs: readonly RunOut[],
    now: Date,
    offset: number,
    hours: number = CHART_HOURS,
): HourBucket[] {
    const first = hourStart(now.getTime(), offset) - (hours - 1) * HOUR_MS
    const buckets: HourBucket[] = Array.from({ length: hours }, (_, index) => {
        const start = first + index * HOUR_MS
        return { start, hour: hourOf(start, offset), succeeded: 0, withErrors: 0, failed: 0, total: 0 }
    })
    for (const run of runs) {
        const at = Date.parse(run.created_at)
        if (Number.isNaN(at)) continue
        const index = Math.floor((at - first) / HOUR_MS)
        if (index < 0 || index >= hours) continue
        const bucket = buckets[index]
        bucket.total += 1
        if (run.status === 'succeeded') bucket.succeeded += 1
        else if (run.status === 'completed_with_errors') bucket.withErrors += 1
        else if (run.status === 'failed') bucket.failed += 1
    }
    return buckets
}

/** How tall one hour's stack is, which is the three outcomes the chart draws and no others. */
export function stackOf(bucket: HourBucket): number {
    return bucket.succeeded + bucket.withErrors + bucket.failed
}

/** The tallest stack in the chart, which is what every bar is drawn as a fraction of. */
export function tallest(buckets: readonly HourBucket[]): number {
    return buckets.reduce((most, bucket) => Math.max(most, stackOf(bucket)), 0)
}

/** What the chart amounts to, for the reader who is hearing it rather than seeing it. */
export function chartSummary(buckets: readonly HourBucket[]): string {
    const settled = (pick: (bucket: HourBucket) => number) =>
        buckets.reduce((sum, bucket) => sum + pick(bucket), 0)
    const total = settled((bucket) => bucket.total)
    if (total === 0) return 'No run was started in the last 24 hours.'
    const parts = [
        `${String(settled((bucket) => bucket.succeeded))} succeeded`,
        `${String(settled((bucket) => bucket.withErrors))} finished with errors`,
        `${String(settled((bucket) => bucket.failed))} failed`,
    ]
    return `${String(total)} runs started in the last 24 hours, by the hour: ${parts.join(', ')}.`
}

/** Whether a row of the health panel is a worker or a connection. */
export type HealthKind = 'worker' | 'connection'

/** One thing this instance depends on, and whether it is well. */
export interface HealthRow {
    id: string
    kind: HealthKind
    /** What it is called: a worker's name, a connection's code. */
    label: string
    tone: TileTone
    /** The one line on the right, which is what it said the last time anything asked. */
    detail: string
    /** When that was, where it is a fact this row has. */
    at: string | null
}

/**
 * The workers and the connections as one list of rows.
 *
 * WORKERS FIRST, BECAUSE NOTHING RUNS WITHOUT ONE. A connection that will not answer stops one
 * pipeline; a fleet that has gone quiet stops every one of them.
 *
 * A ROW SAYS THE FACT WORTH KNOWING. A worker with nothing to report says what it is and how
 * much it can take; one with something to report says that instead, and carries when it was
 * last heard from. The row is headed by the worker, so what is wrong is stated without naming
 * it a second time.
 */
export function healthRows(
    workers: readonly WorkerOut[],
    connections: readonly ConnectionOut[],
): HealthRow[] {
    const fleet = workers.map((worker): HealthRow => {
        const concern = concernOf(worker)
        return {
            id: worker.id,
            kind: 'worker',
            label: worker.name,
            tone: concern === null ? 'good' : concernTone(concern),
            detail:
                concern === null
                    ? `worker · ${String(worker.concurrency)} ${worker.concurrency === 1 ? 'slot' : 'slots'}`
                    : concernSaid(concern),
            at: concern === null ? null : worker.last_seen_at,
        }
    })
    const held = connections.map((connection): HealthRow => {
        const healthy = connection.last_check_healthy
        return {
            id: connection.id,
            kind: 'connection',
            label: connection.code,
            tone: healthy === null ? 'neutral' : healthy ? 'good' : 'critical',
            detail:
                healthy === null
                    ? 'never checked'
                    : (connection.last_check_detail ?? (healthy ? 'healthy' : 'did not answer')),
            at: connection.last_check_at,
        }
    })
    return [...fleet, ...held]
}

/**
 * The one line along the foot of the panel: what is not perfect, or that nothing is wrong.
 *
 * ONLY WHAT IS NOT PERFECT. "3 of 3 connections healthy" spends a clause saying nothing
 * happened, and a reader has to read it to find that out -- so a half that is entirely well is
 * left out, and a screen where both halves are well says so in one sentence.
 *
 * The connections half is `connectionsNote`, which is what the connections screen and the admin
 * tile say as well: a credential nothing has checked yet is not one that answered wrongly.
 */
export function healthNote(workers: readonly WorkerOut[], connections: readonly ConnectionOut[]): string {
    const well = workers.filter((worker) => concernOf(worker) === null).length
    const { healthy, total } = connectionsHealth(connections)
    const said: string[] = []
    if (workers.length === 0) said.push('no worker has registered')
    else if (well < workers.length) said.push(`${String(well)} of ${String(workers.length)} workers healthy`)
    if (healthy < total) {
        const note = connectionsNote(connections, 'connections')
        if (note !== null) said.push(note)
    }
    if (said.length > 0) {
        const line = said.join(' · ')
        return `${line.charAt(0).toUpperCase()}${line.slice(1)}.`
    }
    if (connections.length === 0) return 'Every worker is healthy, and this instance holds no connections.'
    return 'Every worker and every connection is healthy.'
}

/** How many upcoming firings the screen lists. */
export const FIRE_ROWS = 6

/**
 * What is running or waiting to be claimed, newest first.
 *
 * TWO LISTING CALLS AND NO MORE, and neither of them is windowed. `GET /runs` narrows to one
 * status at a time, and a run that has been going since before the window would be missing from
 * a read that asked for the last day -- which is the one run somebody opening this screen most
 * wants to see.
 */
export function liveRuns(
    running: readonly RunOut[],
    queued: readonly RunOut[],
    rows: number = LIVE_ROWS,
): RunOut[] {
    return [...running, ...queued]
        .toSorted((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at))
        .slice(0, rows)
}

/** One schedule, and the pipeline whose address it hangs off. */
export interface PipelineSchedule {
    pipeline: string
    schedule: ScheduleOut
}

/** One firing that is still ahead: which schedule, on which pipeline, and when. */
export interface NextFire extends PipelineSchedule {
    /** The instant it fires at, which a paused schedule does not have. */
    at: string
}

/**
 * The firings still ahead, soonest first.
 *
 * A PAUSED SCHEDULE IS NOT A FIRING. Pausing keeps the computed `next_fire_at` on the row so
 * resuming has somewhere to carry on from, and a screen headed "next fires" that listed one
 * would promise a firing the scheduler will not make. `nextFireView` is where that is decided,
 * once, and this reads it rather than the flag.
 */
export function nextFires(schedules: readonly PipelineSchedule[], rows: number = FIRE_ROWS): NextFire[] {
    return schedules
        .flatMap((held) => {
            const view = nextFireView(held.schedule)
            return view.kind === 'due' ? [{ ...held, at: view.at }] : []
        })
        .toSorted((left, right) => Date.parse(left.at) - Date.parse(right.at))
        .slice(0, rows)
}

/**
 * Every schedule on the pipelines of one page.
 *
 * A SCHEDULE HANGS OFF ITS PIPELINE and this API has no listing of every schedule on the
 * instance, so the walk is the triggers screen's: one page of pipelines, then the schedules of
 * the ones the listing already counted at least one of. A pipeline the listing says has none is
 * not asked about, so an instance of a hundred idle pipelines costs this screen no requests at
 * all.
 */
export async function readPipelineSchedules(pipelines: readonly PipelineOut[]): Promise<PipelineSchedule[]> {
    const carrying = pipelines.filter((row) => row.schedules > 0)
    const found = await Promise.all(
        carrying.map(async (pipeline) => {
            const page = await readSchedules(pipeline.code, null)
            return page.items.map((schedule) => ({ pipeline: pipeline.code, schedule }))
        }),
    )
    return found.flat()
}

/** The pipelines listing, and every schedule hanging off it, which is one read on this screen. */
export async function readSchedulesAhead(): Promise<{
    pipelines: PipelineOut[]
    schedules: PipelineSchedule[]
}> {
    const pipelines = await readPipelines(null)
    return { pipelines: pipelines.items, schedules: await readPipelineSchedules(pipelines.items) }
}
