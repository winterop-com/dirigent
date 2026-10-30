/**
 * The trigger resources, as this bundle reads them.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface here mirrors a pydantic model in
 * `dirigent_client.schemas.triggers` member for member.
 *
 * A TRIGGER BELONGS TO A PIPELINE, AND SO DOES ITS ADDRESS. This API has no listing of every
 * schedule on the instance: schedules hang off `/pipelines/{code}/triggers/...`. So the
 * screen's walk is a walk over pipelines -- one page of pipelines, then the schedules of the
 * ones the listing already counted at least one of -- and the cursor it carries is the
 * pipelines cursor. A pipeline the listing says has no schedules is not asked about, so an
 * instance of a hundred idle pipelines is still one request.
 */

import { apiJson, apiSend, type JsonMap, type Page } from '@/lib/api'
import { LABELS } from '@/lib/labels'
import { PAGE } from '@/lib/paging'
import type { RunPriority } from '@/lib/runs'
import { readPipelines, type PipelineOut } from '@/lib/pipelines'

/** How a schedule computes its next firing. `ScheduleKind`. */
export type ScheduleKind = 'cron' | 'interval' | 'one_time'

/** What one scheduler tick decided about one due schedule. `FiringOutcome`. */
export type FiringOutcome = 'fired' | 'queued' | 'replaced' | 'skipped' | 'failed'

/** A schedule as a listing shows it. `ScheduleOut`. */
export interface ScheduleOut {
    id: string
    /** The key this schedule is addressed by, under the pipeline it fires. */
    code: string
    /** What to call it on screen, when somebody gave it something to be called. */
    name: string | null
    description: string | null
    kind: ScheduleKind
    cron: string | null
    /** The interval as the humane duration it was declared as, such as `15m`. */
    interval: string | null
    at: string | null
    timezone: string
    params: JsonMap
    /** The priority every fired run carries, or null where it takes the pipeline's own. */
    priority: RunPriority | null
    paused: boolean
    managed: boolean
    /** The triggers document that declares this row, or null when the pipeline's own does. */
    trigger_document: string | null
    next_fire_at: string | null
    last_fired_at: string | null
    created_at: string
}

/** One recorded firing: what it was due for, and what came of it. `FiringOut`. */
export interface FiringOut {
    id: number
    scheduled_for: string
    created_at: string
    outcome: FiringOutcome
    misfired: boolean
    run_id: string | null
    detail: string | null
}

/** One schedule, with the pipeline it fires and the last thing it did. */
export interface ScheduleRow {
    pipeline: string
    /** What that pipeline is called, which heads the reference to it. */
    pipelineName: string | null
    schedule: ScheduleOut
    /** The newest firing, or nothing for a schedule that has never fired. */
    latest: FiringOut | null
}

/** What one row is keyed by. */
export function scheduleId(row: ScheduleRow): string {
    return row.schedule.id
}

/** What the status bar says for as long as this screen is mounted. */

const triggersPath = (pipeline: string) => `/pipelines/${encodeURIComponent(pipeline)}/triggers`

/** Read one page of a pipeline's schedules. */
export function readSchedules(pipeline: string, after: string | null): Promise<Page<ScheduleOut>> {
    return apiJson<Page<ScheduleOut>>(`${triggersPath(pipeline)}/schedules${cursor(after)}`)
}

/** Read what a schedule has actually done, newest first, including what it skipped. */
export function readFirings(
    pipeline: string,
    schedule: string,
    after: string | null,
    limit = PAGE,
): Promise<Page<FiringOut>> {
    return apiJson<Page<FiringOut>>(
        `${triggersPath(pipeline)}/schedules/${encodeURIComponent(schedule)}/firings${cursor(after, limit)}`,
    )
}

/** The query one page of any of these listings is asked for with. */
function cursor(after: string | null, limit = PAGE): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (after !== null) query.set('after', after)
    return `?${query.toString()}`
}

/** Stop a schedule firing, or start it again, without losing it or its history. */
export function setSchedulePaused(pipeline: string, schedule: string, paused: boolean): Promise<ScheduleOut> {
    const verb = paused ? '$pause' : '$resume'
    return apiJson<ScheduleOut>(
        `${triggersPath(pipeline)}/schedules/${encodeURIComponent(schedule)}/${verb}`,
        {
            method: 'POST',
        },
    )
}

/** A schedule as a caller declares it: exactly one clock, in its own timezone. `ScheduleIn`. */
export interface ScheduleIn {
    code: string
    name?: string | null
    description?: string | null
    cron?: string | null
    interval?: string | null
    at?: string | null
    timezone: string
    params: JsonMap
    /** The priority every fired run carries. Omitted takes the pipeline's own. */
    priority?: RunPriority | null
}

/** Declare a schedule on a pipeline and compute when it first fires. */
export function createSchedule(pipeline: string, payload: ScheduleIn): Promise<ScheduleOut> {
    return apiSend<ScheduleOut>(`${triggersPath(pipeline)}/schedules`, 'POST', payload)
}

/** A clock as it is being written, for reading back what it would fire. `SchedulePreviewRequest`. */
export interface SchedulePreviewRequest {
    cron?: string | null
    interval?: string | null
    at?: string | null
    timezone: string
}

/** The next firings of a clock nothing has declared yet, oldest first. `SchedulePreview`. */
export interface SchedulePreview {
    firings: string[]
}

/**
 * Read back what a clock would fire, before anything has been declared.
 *
 * THE ARITHMETIC IS THE SCHEDULER'S. The firings are computed by the same core code that
 * advances a stored schedule, so what the dialog promises and what the instance would do
 * cannot disagree; an expression nothing can read is a refusal carrying the parser's sentence.
 */
export function previewSchedule(clock: SchedulePreviewRequest): Promise<SchedulePreview> {
    return apiSend<SchedulePreview>('/schedules/$preview', 'POST', clock)
}

/**
 * One page of the schedules listing: a page of pipelines, and the schedules of the ones that have any.
 *
 * The newest firing is read for the schedules that have one, because a listing that said only
 * when a schedule last fired would not say whether that firing started anything.
 */
export async function readSchedulePage(after: string | null): Promise<Page<ScheduleRow>> {
    const pipelines = await readPipelines(after)
    const carrying = pipelines.items.filter((row) => row.schedules > 0)
    const found = await Promise.all(carrying.map(schedulesOf))
    return { items: found.flat(), next: pipelines.next }
}

/** Every schedule of one pipeline, with the last thing each of them did. */
async function schedulesOf(pipeline: PipelineOut): Promise<ScheduleRow[]> {
    const schedules = await readSchedules(pipeline.code, null)
    return Promise.all(
        schedules.items.map(async (schedule): Promise<ScheduleRow> => {
            const latest =
                schedule.last_fired_at === null
                    ? null
                    : await newest(readFirings(pipeline.code, schedule.code, null, 1))
            return {
                pipeline: pipeline.code,
                pipelineName: pipeline.name,
                schedule,
                latest,
            }
        }),
    )
}

/**
 * The first row of a history page, or nothing.
 *
 * A history a reader cannot see is not worth failing a screen for: a refusal here leaves the
 * row saying when it last fired without saying what came of it.
 */
async function newest<T>(reading: Promise<Page<T>>): Promise<T | null> {
    try {
        return (await reading).items[0] ?? null
    } catch {
        return null
    }
}

/** What a schedule's next firing amounts to on screen. */
export type NextFireView =
    /** Its clock names no further moment at all, which is a one-time schedule that has fired. */
    | { kind: 'none' }
    /** It holds a computed instant it will not fire at, because somebody stopped it. */
    | { kind: 'paused' }
    /** It fires next at this instant. */
    | { kind: 'due'; at: string }

/**
 * When a schedule fires next, or why it does not.
 *
 * A PAUSED SCHEDULE FIRES AT NO INSTANT. Pausing keeps the computed `next_fire_at` on the row --
 * resuming recomputes it from now, so it has to have somewhere to carry on from -- and a screen
 * that drew it would promise a firing the scheduler will not make.
 *
 * A SPENT CLOCK IS NOT A PAUSED ONE, THOUGH THE COLUMN SAYS SO. A one-time schedule pauses
 * itself once its moment has gone by rather than being deleted, so that its parameters and its
 * firings stay readable; what is true of it is that nothing is scheduled, which is why an
 * absent instant is read before the flag rather than after it.
 */
export function nextFireView(schedule: Pick<ScheduleOut, 'paused' | 'next_fire_at'>): NextFireView {
    if (schedule.next_fire_at === null) return { kind: 'none' }
    if (schedule.paused) return { kind: 'paused' }
    return { kind: 'due', at: schedule.next_fire_at }
}

/** A one-time schedule's own moment, and whether it has happened. */
export interface OneTimeView {
    /** The moment it names, read relatively like every other instant in the app. */
    at: string
    /** Whether it already fired, which is what the cell says in front of the instant. */
    fired: boolean
}

/**
 * The moment a one-time schedule names, said as what it is now rather than as a clock string.
 *
 * FIRED IS WHAT THE SCHEDULE DID, NOT WHAT THE CALENDAR SAYS. A moment that has passed with no
 * firing behind it is a schedule the scheduler has yet to reach, so it is `last_fired_at` that
 * decides the word and never the comparison against now.
 */
export function oneTimeView(schedule: Pick<ScheduleOut, 'at' | 'last_fired_at'>): OneTimeView | null {
    if (schedule.at === null) return null
    return { at: schedule.at, fired: schedule.last_fired_at !== null }
}

/** The one clock a schedule has, and how it is drawn. */
export interface ClockView {
    kind: 'cron' | 'interval' | 'at' | 'none'
    /** What the cell says. */
    text: string
    /** Whether it is a machine's own string, which is what wears the mono face. */
    mono: boolean
}

/**
 * Which clock a schedule fires on, in the order the API fills them in.
 *
 * A schedule has exactly one -- the core refuses a declaration with two -- but the wire shape
 * carries all three fields, so the reading is by precedence rather than by which happen to be
 * null: cron first, then an interval, then a calendar moment. A row that somehow arrived with
 * none of them says so instead of rendering an empty cell.
 */
export function clockOf(schedule: Pick<ScheduleOut, 'cron' | 'interval' | 'at'>): ClockView {
    if (schedule.cron !== null) return { kind: 'cron', text: schedule.cron, mono: true }
    if (schedule.interval !== null)
        return { kind: 'interval', text: LABELS.triggers.schedule.every(schedule.interval), mono: false }
    if (schedule.at !== null) return { kind: 'at', text: schedule.at, mono: false }
    return { kind: 'none', text: LABELS.triggers.schedule.no_clock, mono: false }
}

/** How loudly one outcome is drawn. The tones are the semantic aliases in index.css. */
export type OutcomeTone = 'good' | 'warn' | 'critical' | 'quiet'

/** What the last-firing cell draws. */
export interface FiringView {
    tone: OutcomeTone
    /** The outcome in the API's own word, with a misfire said as a misfire. */
    label: string
    /** The run that firing started, or nothing. */
    runId: string | null
    /** Why it went the way it did, or nothing. */
    detail: string | null
}

/**
 * What one firing amounts to on screen.
 *
 * A MISFIRE IS AMBER WHATEVER ELSE IT WAS. A firing the scheduler reached late is a firing
 * that happened, so its outcome is still the outcome; that it was late is the thing worth
 * seeing, and it is what decides the colour.
 */
export function firingView(firing: FiringOut): FiringView {
    const said = FIRING_WORDS[firing.outcome]
    return {
        tone: firing.misfired ? 'warn' : TONES[firing.outcome],
        label: firing.misfired ? LABELS.triggers.schedule.misfired(said) : said,
        runId: firing.run_id,
        detail: firing.detail,
    }
}

/**
 * What each outcome is called, keyed by the wire's own value.
 *
 * The word and the wire's value are the same characters, and the table is still the point: a
 * cell that drew `firing.outcome` was drawing a word that had never been near the catalogue,
 * so no review saw it and no second language could reach it.
 */
const FIRING_WORDS: Record<FiringOutcome, string> = LABELS.triggers.schedule.outcome

/** What each outcome is worth, before a misfire has its say. */
const TONES: Record<FiringOutcome, OutcomeTone> = {
    fired: 'good',
    queued: 'quiet',
    replaced: 'quiet',
    skipped: 'quiet',
    failed: 'critical',
}
