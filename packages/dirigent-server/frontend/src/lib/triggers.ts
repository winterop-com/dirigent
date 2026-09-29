/**
 * The trigger resources, as this bundle reads them.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface here mirrors a pydantic model in
 * `dirigent_client.schemas.triggers` member for member.
 *
 * A TRIGGER BELONGS TO A PIPELINE, AND SO DOES ITS ADDRESS. This API has no listing of every
 * schedule on the instance: schedules, webhooks and watches hang off `/pipelines/{code}/triggers/...`.
 * So the screen's walk is a walk over pipelines -- one page of pipelines, then the triggers of
 * the ones the listing already counted at least one of -- and the cursor it carries is the
 * pipelines cursor. A pipeline the listing says has no triggers of any kind is not asked
 * about, so an instance of a hundred idle pipelines is still one request.
 *
 * THE ROWS OF EVERY KIND ARE ONE LISTING. The sections grow together because all are read
 * from the same page of pipelines, which is what lets the screen hold them in one `usePaged`
 * and state one honest count along each foot.
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

/** What the intake endpoint did with one delivery. `WebhookOutcome`. */
export type WebhookOutcome = 'accepted' | 'skipped' | 'rejected'

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

/** A webhook as a listing shows it: everything about it except the token. `WebhookOut`. */
export interface WebhookOut {
    id: string
    /** The key this webhook is addressed by, under the pipeline it fires. */
    code: string
    /** What to call it on screen, when somebody gave it something to be called. */
    name: string | null
    description: string | null
    token_prefix: string
    params_from_payload: Record<string, string>
    signed: boolean
    active: boolean
    managed: boolean
    /** The triggers document that declares this row, or null when the pipeline's own does. */
    trigger_document: string | null
    rate_limit_per_minute: number
    /** The priority every accepted delivery's run carries, or null for the pipeline's own. */
    priority: RunPriority | null
    last_delivery_at: string | null
    created_at: string
}

/** A freshly minted webhook token, answered once and never readable again. `WebhookTokenOut`. */
export interface WebhookTokenOut {
    webhook_id: string
    code: string
    token: string
    prefix: string
    /** Where to POST, so a caller is configured without assembling the path by hand. */
    url_path: string
}

/** One inbound delivery, and what came of it. `DeliveryOut`. */
export interface DeliveryOut {
    id: number
    created_at: string
    outcome: WebhookOutcome
    run_id: string | null
    reason: string | null
    mapped_params: JsonMap | null
    source: string | null
}

/** A watch as a listing shows it: what it waits on, and how its waits are going. `WatchOut`. */
export interface WatchOut {
    id: string
    /** The key this watch is addressed by, under the pipeline it fires. */
    code: string
    /** What to call it on screen, when somebody gave it something to be called. */
    name: string | null
    description: string | null
    /** The root sensor step every run it arms waits on. */
    step: string
    params: JsonMap
    paused: boolean
    managed: boolean
    /** The triggers document that declares this row, or null when the pipeline's own does. */
    trigger_document: string | null
    /** Where the last successful poke of the watched step left off, which the next run starts from. */
    cursor: JsonMap | null
    /** The run waiting on the sensor now, or null between one run and the next. */
    waiting_run_id: string | null
    /** How many waits in a row have ended without the sensor succeeding. */
    failures: number
    /** Why the last wait ended without the sensor succeeding, or null once one has succeeded since. */
    last_error: string | null
    last_error_at: string | null
    /** When a watch backing off after a failure arms its next run. */
    rearm_at: string | null
    last_armed_at: string | null
    created_at: string
}

/** One schedule, with the pipeline it fires and the last thing it did. */
export interface ScheduleRow {
    kind: 'schedule'
    pipeline: string
    /** What that pipeline is called, which heads the reference to it. */
    pipelineName: string | null
    schedule: ScheduleOut
    /** The newest firing, or nothing for a schedule that has never fired. */
    latest: FiringOut | null
}

/** One webhook, with the pipeline it fires and the last delivery it took. */
export interface WebhookRow {
    kind: 'webhook'
    pipeline: string
    /** What that pipeline is called, which heads the reference to it. */
    pipelineName: string | null
    webhook: WebhookOut
    /** The newest delivery, or nothing for a webhook nothing has been sent to. */
    latest: DeliveryOut | null
}

/** One watch, with the pipeline it keeps a run of waiting. */
export interface WatchRow {
    kind: 'watch'
    pipeline: string
    /** What that pipeline is called, which heads the reference to it. */
    pipelineName: string | null
    watch: WatchOut
}

/** One row of the triggers screen, which holds every kind in one walk. */
export type TriggerRow = ScheduleRow | WebhookRow | WatchRow

/** What one row is keyed by, which has to separate rows of different kinds that share an id. */
export function triggerId(row: TriggerRow): string {
    switch (row.kind) {
        case 'schedule':
            return `schedule:${row.schedule.id}`
        case 'webhook':
            return `webhook:${row.webhook.id}`
        case 'watch':
            return `watch:${row.watch.id}`
    }
}

/** What the status bar says for as long as this screen is mounted. */

const triggersPath = (pipeline: string) => `/pipelines/${encodeURIComponent(pipeline)}/triggers`

/** Read one page of a pipeline's schedules. */
export function readSchedules(pipeline: string, after: string | null): Promise<Page<ScheduleOut>> {
    return apiJson<Page<ScheduleOut>>(`${triggersPath(pipeline)}/schedules${cursor(after)}`)
}

/** Read one page of a pipeline's webhooks. */
export function readWebhooks(pipeline: string, after: string | null): Promise<Page<WebhookOut>> {
    return apiJson<Page<WebhookOut>>(`${triggersPath(pipeline)}/webhooks${cursor(after)}`)
}

/** Read one page of a pipeline's watches. */
export function readWatches(pipeline: string, after: string | null): Promise<Page<WatchOut>> {
    return apiJson<Page<WatchOut>>(`${triggersPath(pipeline)}/watches${cursor(after)}`)
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

/** Read what has arrived at a webhook, newest first, refusals included. */
export function readDeliveries(
    pipeline: string,
    webhook: string,
    after: string | null,
    limit = PAGE,
): Promise<Page<DeliveryOut>> {
    return apiJson<Page<DeliveryOut>>(
        `${triggersPath(pipeline)}/webhooks/${encodeURIComponent(webhook)}/deliveries${cursor(after, limit)}`,
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

/** Stop a watch, cancelling the run it has waiting, or start it again from where it left off. */
export function setWatchPaused(pipeline: string, watch: string, paused: boolean): Promise<WatchOut> {
    const verb = paused ? '$pause' : '$resume'
    return apiJson<WatchOut>(`${triggersPath(pipeline)}/watches/${encodeURIComponent(watch)}/${verb}`, {
        method: 'POST',
    })
}

/** Refuse deliveries, or accept them again, on the token that was already issued. */
export function setWebhookActive(pipeline: string, webhook: string, active: boolean): Promise<WebhookOut> {
    const verb = active ? '$enable' : '$disable'
    return apiJson<WebhookOut>(`${triggersPath(pipeline)}/webhooks/${encodeURIComponent(webhook)}/${verb}`, {
        method: 'POST',
    })
}

/** Mint a new token and forget the old one immediately; every caller has to be updated. */
export function rotateWebhookToken(pipeline: string, webhook: string): Promise<WebhookTokenOut> {
    return apiJson<WebhookTokenOut>(
        `${triggersPath(pipeline)}/webhooks/${encodeURIComponent(webhook)}/$rotate-token`,
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

/** A webhook as a caller declares it; the token is never supplied, only minted. `WebhookIn`. */
export interface WebhookIn {
    code: string
    name?: string | null
    description?: string | null
    params_from_payload: Record<string, string>
    hmac_secret: string | null
    rate_limit_per_minute: number
    /** The priority every accepted delivery's run carries. Omitted takes the pipeline's own. */
    priority?: RunPriority | null
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

/** Declare a webhook and read back its token, which is answered here and nowhere else again. */
export function createWebhook(pipeline: string, payload: WebhookIn): Promise<WebhookTokenOut> {
    return apiSend<WebhookTokenOut>(`${triggersPath(pipeline)}/webhooks`, 'POST', payload)
}

/**
 * One page of the triggers listing: a page of pipelines, and the triggers of the ones that have any.
 *
 * The newest firing and the newest delivery are read for the rows that have one, because a
 * listing that said only when a schedule last fired would not say whether that firing started
 * anything.
 */
export async function readTriggerPage(after: string | null): Promise<Page<TriggerRow>> {
    const pipelines = await readPipelines(after)
    const carrying = pipelines.items.filter((row) => row.schedules > 0 || row.webhooks > 0 || row.watches > 0)
    const found = await Promise.all(carrying.map(triggersOf))
    return { items: found.flat(), next: pipelines.next }
}

/** Every trigger of one pipeline, with the last thing each of them did. */
async function triggersOf(pipeline: PipelineOut): Promise<TriggerRow[]> {
    const [schedules, webhooks, watches] = await Promise.all([
        pipeline.schedules > 0 ? readSchedules(pipeline.code, null) : empty<ScheduleOut>(),
        pipeline.webhooks > 0 ? readWebhooks(pipeline.code, null) : empty<WebhookOut>(),
        pipeline.watches > 0 ? readWatches(pipeline.code, null) : empty<WatchOut>(),
    ])
    const scheduleRows = await Promise.all(
        schedules.items.map(async (schedule): Promise<ScheduleRow> => {
            const latest =
                schedule.last_fired_at === null
                    ? null
                    : await newest(readFirings(pipeline.code, schedule.code, null, 1))
            return {
                kind: 'schedule',
                pipeline: pipeline.code,
                pipelineName: pipeline.name,
                schedule,
                latest,
            }
        }),
    )
    const webhookRows = await Promise.all(
        webhooks.items.map(async (webhook): Promise<WebhookRow> => {
            const latest =
                webhook.last_delivery_at === null
                    ? null
                    : await newest(readDeliveries(pipeline.code, webhook.code, null, 1))
            return { kind: 'webhook', pipeline: pipeline.code, pipelineName: pipeline.name, webhook, latest }
        }),
    )
    const watchRows = watches.items.map((watch): WatchRow => ({
        kind: 'watch',
        pipeline: pipeline.code,
        pipelineName: pipeline.name,
        watch,
    }))
    return [...scheduleRows, ...webhookRows, ...watchRows]
}

/** A listing that was never asked for. */
function empty<T>(): Promise<Page<T>> {
    return Promise.resolve({ items: [], next: null })
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

/** What the last-delivery cell draws. */
export interface DeliveryView {
    tone: OutcomeTone
    label: string
    runId: string | null
    /** Why a delivery was refused or dropped, which is the muted half of the cell. */
    reason: string | null
}

/** What one delivery amounts to on screen: the run it started, or why it started none. */
export function deliveryView(delivery: DeliveryOut): DeliveryView {
    const tone: OutcomeTone =
        delivery.outcome === 'accepted' ? 'good' : delivery.outcome === 'rejected' ? 'critical' : 'quiet'
    return {
        tone,
        label: DELIVERY_WORDS[delivery.outcome],
        runId: delivery.run_id,
        reason: delivery.reason,
    }
}

/** What each outcome is called, keyed by the wire's own value. `FIRING_WORDS`' reason. */
const DELIVERY_WORDS: Record<WebhookOutcome, string> = LABELS.triggers.webhook.outcome

/** How much of a webhook's token a listing may show, which is the prefix and nothing after it. */
export function hookPath(webhook: Pick<WebhookOut, 'token_prefix'>): string {
    return `/hooks/${webhook.token_prefix}…`
}

/** Whether a webhook proves who sent a delivery, in the words the column uses. */
export function signing(webhook: Pick<WebhookOut, 'signed'>): string {
    return webhook.signed ? LABELS.triggers.webhook.signed : LABELS.triggers.webhook.unsigned
}

/** How a watch's waits are going, in the one reading the listing and the panel both draw. */
export type WatchView =
    /** Somebody stopped it, so nothing is waiting and nothing will be armed. */
    | { kind: 'paused'; tone: OutcomeTone }
    /** A run is waiting on the sensor now. */
    | { kind: 'waiting'; tone: OutcomeTone; runId: string }
    /** A wait failed, and the next run is armed at this instant. */
    | { kind: 'backing-off'; tone: OutcomeTone; until: string }
    /** Nothing is waiting and nothing holds it back: the next tick arms it. */
    | { kind: 'arming'; tone: OutcomeTone }

/**
 * What a watch is doing, read in the order the instance decides it.
 *
 * PAUSED IS READ FIRST. A paused watch keeps its cursor and its last error, and neither is what
 * is true of it now: it has nothing waiting and will arm nothing until it is resumed.
 */
export function watchView(watch: Pick<WatchOut, 'paused' | 'waiting_run_id' | 'rearm_at'>): WatchView {
    if (watch.paused) return { kind: 'paused', tone: 'quiet' }
    if (watch.waiting_run_id !== null) return { kind: 'waiting', tone: 'good', runId: watch.waiting_run_id }
    if (watch.rearm_at !== null) return { kind: 'backing-off', tone: 'warn', until: watch.rearm_at }
    return { kind: 'arming', tone: 'quiet' }
}
