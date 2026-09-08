/**
 * The trigger resources, as this bundle reads them.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface here mirrors a pydantic model in
 * `dirigent_client.schemas.triggers` member for member.
 *
 * A TRIGGER BELONGS TO A PIPELINE, AND SO DOES ITS ADDRESS. This API has no listing of every
 * schedule on the instance: schedules and webhooks hang off `/pipelines/{code}/triggers/...`.
 * So the screen's walk is a walk over pipelines -- one page of pipelines, then the triggers of
 * the ones the listing already counted at least one of -- and the cursor it carries is the
 * pipelines cursor. A pipeline the listing says has no schedules and no webhooks is not asked
 * about, so an instance of a hundred idle pipelines is still one request.
 *
 * THE ROWS OF BOTH KINDS ARE ONE LISTING. Both sections grow together because both are read
 * from the same page of pipelines, which is what lets the screen hold them in one `usePaged`
 * and state one honest count along each foot.
 */

import { apiJson, apiSend, type JsonMap, type Page } from '@/lib/api'
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

/** One schedule, with the pipeline it fires and the last thing it did. */
export interface ScheduleRow {
    kind: 'schedule'
    pipeline: string
    schedule: ScheduleOut
    /** The newest firing, or nothing for a schedule that has never fired. */
    latest: FiringOut | null
}

/** One webhook, with the pipeline it fires and the last delivery it took. */
export interface WebhookRow {
    kind: 'webhook'
    pipeline: string
    webhook: WebhookOut
    /** The newest delivery, or nothing for a webhook nothing has been sent to. */
    latest: DeliveryOut | null
}

/** One row of the triggers screen, which holds both kinds in one walk. */
export type TriggerRow = ScheduleRow | WebhookRow

/** What one row is keyed by, which has to separate a schedule from a webhook of the same id. */
export function triggerId(row: TriggerRow): string {
    return row.kind === 'schedule' ? `schedule:${row.schedule.id}` : `webhook:${row.webhook.id}`
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

/** Read what a schedule has actually done, newest first, including what it skipped. */
export function readFirings(pipeline: string, schedule: string, after: string | null, limit = PAGE): Promise<Page<FiringOut>> {
    return apiJson<Page<FiringOut>>(`${triggersPath(pipeline)}/schedules/${encodeURIComponent(schedule)}/firings${cursor(after, limit)}`)
}

/** Read what has arrived at a webhook, newest first, refusals included. */
export function readDeliveries(pipeline: string, webhook: string, after: string | null, limit = PAGE): Promise<Page<DeliveryOut>> {
    return apiJson<Page<DeliveryOut>>(`${triggersPath(pipeline)}/webhooks/${encodeURIComponent(webhook)}/deliveries${cursor(after, limit)}`)
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
    return apiJson<ScheduleOut>(`${triggersPath(pipeline)}/schedules/${encodeURIComponent(schedule)}/${verb}`, {
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
    return apiJson<WebhookTokenOut>(`${triggersPath(pipeline)}/webhooks/${encodeURIComponent(webhook)}/$rotate-token`, {
        method: 'POST',
    })
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
    const carrying = pipelines.items.filter((row) => row.schedules > 0 || row.webhooks > 0)
    const found = await Promise.all(carrying.map(triggersOf))
    return { items: found.flat(), next: pipelines.next }
}

/** Every trigger of one pipeline, with the last thing each of them did. */
async function triggersOf(pipeline: PipelineOut): Promise<TriggerRow[]> {
    const [schedules, webhooks] = await Promise.all([
        pipeline.schedules > 0 ? readSchedules(pipeline.code, null) : empty<ScheduleOut>(),
        pipeline.webhooks > 0 ? readWebhooks(pipeline.code, null) : empty<WebhookOut>(),
    ])
    const scheduleRows = await Promise.all(
        schedules.items.map(async (schedule): Promise<ScheduleRow> => {
            const latest =
                schedule.last_fired_at === null ? null : await newest(readFirings(pipeline.code, schedule.code, null, 1))
            return { kind: 'schedule', pipeline: pipeline.code, schedule, latest }
        }),
    )
    const webhookRows = await Promise.all(
        webhooks.items.map(async (webhook): Promise<WebhookRow> => {
            const latest =
                webhook.last_delivery_at === null ? null : await newest(readDeliveries(pipeline.code, webhook.code, null, 1))
            return { kind: 'webhook', pipeline: pipeline.code, webhook, latest }
        }),
    )
    return [...scheduleRows, ...webhookRows]
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
    if (schedule.interval !== null) return { kind: 'interval', text: `every ${schedule.interval}`, mono: false }
    if (schedule.at !== null) return { kind: 'at', text: schedule.at, mono: false }
    return { kind: 'none', text: 'no clock', mono: false }
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
    return {
        tone: firing.misfired ? 'warn' : TONES[firing.outcome],
        label: firing.misfired ? `${firing.outcome} (misfired)` : firing.outcome,
        runId: firing.run_id,
        detail: firing.detail,
    }
}

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
    return { tone, label: delivery.outcome, runId: delivery.run_id, reason: delivery.reason }
}

/** How much of a webhook's token a listing may show, which is the prefix and nothing after it. */
export function hookPath(webhook: Pick<WebhookOut, 'token_prefix'>): string {
    return `/hooks/${webhook.token_prefix}…`
}

/** Whether a webhook proves who sent a delivery, in the words the column uses. */
export function signing(webhook: Pick<WebhookOut, 'signed'>): string {
    return webhook.signed ? 'HMAC' : 'unsigned'
}
