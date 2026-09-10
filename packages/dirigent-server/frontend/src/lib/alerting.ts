/**
 * The rules that watch runs, the channels they deliver through, and the queue they leave by.
 *
 * THE FIELD NAMES ARE THE WIRE'S: `AlertRuleOut`, `AlertRuleIn`, `AlertRuleUpdate`,
 * `NotificationOut`, `TestRequest` and `TestQueued` in `dirigent_client.schemas.alerts`, member
 * for member.
 *
 * A NOTIFICATION IS QUEUED, NOT SENT. `POST /alert-rules/$test` answers 202 and a worker
 * delivers on its next pass, so what the screen reports at first is that the message was
 * accepted -- and `readNotification` is how it then watches the row settle.
 *
 * ONLY THE LATEST REFUSAL IS STORED. A notification carries one `error` and a count of
 * attempts, not a row per try, so nothing here can answer what the second attempt said.
 */

import { apiJson, apiSend, type Page } from '@/lib/api'
import { type ConnectionOut } from '@/lib/connections'
import { PAGE } from '@/lib/paging'

/** What a rule watches for. `AlertEvent` in dirigent_client.enums. */
export type AlertEvent = 'run_failed' | 'run_completed_with_errors' | 'run_succeeded' | 'run_stuck'

/** Whether a rule watches everything or one pipeline. `AlertScope`. */
export type AlertScope = 'global' | 'pipeline'

/** Where one queued message is. `NotificationStatus`. */
export type NotificationStatus = 'pending' | 'sending' | 'sent' | 'failed'

/** Every event a rule may bind to, in the order the dialog offers them. */
export const ALERT_EVENTS: readonly AlertEvent[] = [
    'run_failed',
    'run_completed_with_errors',
    'run_succeeded',
    'run_stuck',
]

/** Every state a delivery can be in, in the order the filter offers them. */
export const NOTIFICATION_STATUSES: readonly NotificationStatus[] = ['pending', 'sending', 'sent', 'failed']

/** The one notifier that needs no credential, because it writes to the process log. */
export const LOG_NOTIFIER = 'log'

/** One rule. `AlertRuleOut`. */
export interface AlertRuleOut {
    id: string
    /** The key this rule is addressed by. */
    code: string
    /** What to call it on screen, when somebody gave it something to be called. */
    name: string | null
    description: string | null
    event: AlertEvent
    scope: AlertScope
    /** The pipeline a scoped rule watches, or null for a global one. */
    pipeline: string | null
    notifier: string
    /** The connection this channel delivers through, or null where the channel needs none. */
    connection: string | null
    /** The subject, a Jinja template over the run's facts. */
    template: string | null
    /** The body, a Jinja template over the same facts. */
    body: string | null
    /** A humane duration, such as `5m`, and never a number of seconds. */
    throttle: string
    active: boolean
    /** Held by an operator rather than declared by the rule, and kept across a re-apply. */
    paused: boolean
    last_sent_at: string | null
    created_at: string
}

/** What declaring a rule sends. `AlertRuleIn`. */
export interface AlertRuleIn {
    code: string
    name: string | null
    description: string | null
    event: AlertEvent
    notifier: string
    scope: AlertScope
    pipeline: string | null
    connection: string | null
    template: string | null
    body: string | null
    throttle: string
}

/** How the server spells a duration of nothing, which is what a rule that is not throttled has. */
const NO_THROTTLE = '0s'

/**
 * What the throttle column says, which for a rule that is not throttled is that it is not.
 *
 * "0s" IS A WINDOW NOBODY SET. The zero is the absence of a throttle rather than a very short
 * one, and a column of durations is read as durations -- so the absence is said in the word for
 * it instead.
 */
export function throttleNote(throttle: string): string {
    return throttle === NO_THROTTLE ? 'none' : throttle
}

/** One message the queue holds. `NotificationOut`. */
export interface NotificationOut {
    id: string
    event: AlertEvent
    /** The rule that raised it, or null for a message somebody sent as a test. */
    rule: string | null
    notifier: string
    connection: string | null
    subject: string
    status: NotificationStatus
    attempt: number
    /** The retry budget this instance is configured with, so the count reads as "2 of 5". */
    max_attempts: number
    run_id: string | null
    /** The run's pipeline, so a row names the run by what it is rather than by its id. */
    run_pipeline: string | null
    run_started_at: string | null
    available_at: string
    sent_at: string | null
    /** What the channel said when it last refused. Only the latest one is kept. */
    error: string | null
    created_at: string
}

/** A test message, as `POST /alert-rules/$test` takes one. `TestRequest`. */
export interface TestRequest {
    notifier: string
    connection?: string | null
    subject?: string
    body?: string
}

/** What the server made of a test send. `TestQueued`. */
export interface TestQueued {
    notification_id: string
    notifier: string
    detail: string
}

/** What a rule watches for, in the words a table uses. */
export function eventLabel(event: AlertEvent): string {
    return event.replaceAll('_', ' ')
}

/** What one rule matches, said in one phrase. */
export function matchNote(rule: AlertRuleOut): string {
    const where = rule.scope === 'pipeline' && rule.pipeline !== null ? rule.pipeline : 'every pipeline'
    return `${eventLabel(rule.event)} — ${where}`
}

/** Where a rule delivers: every pipeline, or the one it watches. */
export function scopeNote(rule: AlertRuleOut): string {
    return rule.scope === 'pipeline' && rule.pipeline !== null ? rule.pipeline : 'every pipeline'
}

/** Whether a rule is delivering at all: a paused one matches nothing the engine settles. */
export function ruleLive(rule: AlertRuleOut): boolean {
    return rule.active && !rule.paused
}

/** Report whether nothing will move this delivery again, which is what stops a poll. */
export function deliverySettled(status: NotificationStatus): boolean {
    return status === 'sent' || status === 'failed'
}

/** Where one page of the alert rules listing is read from. */
export function alertRulesPath(after: string | null, limit: number = PAGE): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (after !== null) query.set('after', after)
    return `/alert-rules?${query.toString()}`
}

/** Read one page of alert rules. */
export function readAlertRules(after: string | null): Promise<Page<AlertRuleOut>> {
    return apiJson<Page<AlertRuleOut>>(alertRulesPath(after))
}

/** Declare a rule binding an event at a scope to a channel. */
export function createRule(payload: AlertRuleIn): Promise<AlertRuleOut> {
    return apiSend<AlertRuleOut>('/alert-rules', 'POST', payload)
}

/** Hold a rule's deliveries, or let them resume. The rule itself is left as declared. */
export function setRulePaused(code: string, paused: boolean): Promise<AlertRuleOut> {
    return apiSend<AlertRuleOut>(`/alert-rules/${encodeURIComponent(code)}`, 'PATCH', { paused })
}

/** Remove a rule; the notifications it already raised are kept. */
export function deleteRule(code: string): Promise<void> {
    return apiJson<void>(`/alert-rules/${encodeURIComponent(code)}`, { method: 'DELETE' })
}

/** What narrows the notifications listing. Empty means no filter, the way every listing spells it. */
export interface NotificationFilters {
    status: string
    notifier: string
}

/** No filter at all, which is what the screen opens on. */
export const NO_FILTERS: NotificationFilters = { status: '', notifier: '' }

/** Where one page of the notifications listing is read from. */
export function notificationsPath(
    filters: NotificationFilters,
    after: string | null,
    limit: number = PAGE,
): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (filters.status !== '') query.set('status', filters.status)
    if (filters.notifier !== '') query.set('notifier', filters.notifier)
    if (after !== null) query.set('after', after)
    return `/notifications?${query.toString()}`
}

/** Read one page of notifications, newest first, narrowed by the server rather than here. */
export function readNotifications(
    filters: NotificationFilters,
    after: string | null,
): Promise<Page<NotificationOut>> {
    return apiJson<Page<NotificationOut>>(notificationsPath(filters, after))
}

/** Read one notification, which is how a dialog watches the delivery it just queued. */
export function readNotification(id: string): Promise<NotificationOut> {
    return apiJson<NotificationOut>(`/notifications/${encodeURIComponent(id)}`)
}

/** Make one notification due now: the backoff goes and the attempt counter starts over. */
export function retryNotification(id: string): Promise<NotificationOut> {
    return apiSend<NotificationOut>(`/notifications/${encodeURIComponent(id)}/$retry`, 'POST', {})
}

/** Queue one test message through a notifier. */
export function sendTest(request: TestRequest): Promise<TestQueued> {
    return apiSend<TestQueued>('/alert-rules/$test', 'POST', request)
}

/** One surface the host contributed, of which only the id is read here. `SurfaceEntry`. */
interface Surface {
    id: string
}

/** The host's merged view of every contribution, of which two members are read here. `Catalog`. */
interface Catalog {
    notifiers: Surface[]
    connection_kinds: Surface[]
}

/** Which channels this instance has installed, which is what a rule may name. */
export async function readNotifiers(): Promise<string[]> {
    const catalog = await apiJson<Catalog>('/blocks')
    return catalog.notifiers.map((one) => one.id)
}

/**
 * One channel on the strip: a notifier, and the credential it delivers through.
 *
 * A CHANNEL IS A NOTIFIER TIMES A CONNECTION, not one or the other. `log` needs no credential
 * and is one channel on its own; every other notifier is one channel per connection of its own
 * kind, because that is what a rule names -- and a notifier installed with no connection minted
 * for it is a channel nothing can reach, which is worth saying rather than leaving out.
 */
export interface Channel {
    /** What the strip is keyed by: the notifier, and the connection where there is one. */
    id: string
    notifier: string
    /** The connection's code, or null for the built-in log channel. */
    connection: string | null
    /** Whether this notifier can be reached at all, which for a connection-less one it cannot. */
    reachable: boolean
    last_check_at: string | null
    last_check_healthy: boolean | null
    last_check_detail: string | null
}

/**
 * The channels this instance has, one card each.
 *
 * The log channel is built in and always first: it needs nothing, and an instance with no
 * credential at all still has somewhere an alert goes.
 */
export function channelsOf(notifiers: readonly string[], connections: readonly ConnectionOut[]): Channel[] {
    const channels: Channel[] = []
    for (const notifier of notifiers) {
        if (notifier === LOG_NOTIFIER) {
            channels.push({
                id: notifier,
                notifier,
                connection: null,
                reachable: true,
                last_check_at: null,
                last_check_healthy: null,
                last_check_detail: null,
            })
            continue
        }
        const mine = connections.filter((row) => row.kind === notifier)
        if (mine.length === 0) {
            channels.push({
                id: notifier,
                notifier,
                connection: null,
                reachable: false,
                last_check_at: null,
                last_check_healthy: null,
                last_check_detail: null,
            })
            continue
        }
        for (const row of mine) {
            channels.push({
                id: `${notifier}:${row.code}`,
                notifier,
                connection: row.code,
                reachable: true,
                last_check_at: row.last_check_at,
                last_check_healthy: row.last_check_healthy,
                last_check_detail: row.last_check_detail,
            })
        }
    }
    return channels
}

/** How a channel card reads its own health: what it is, and what it last proved. */
export interface ChannelView {
    tone: 'good' | 'critical' | 'quiet'
    /** The short word on the card, beside the code. */
    label: string
    /** The sentence under it, which is the check's own where there is one. */
    detail: string | null
}

/**
 * What one channel card says about itself.
 *
 * A CHANNEL NOBODY HAS CHECKED IS NOT A HEALTHY ONE. The three states are separate on purpose:
 * a check that failed is the thing this strip exists to surface, and a check that has never run
 * says so rather than borrowing the colour of one that passed.
 */
export function channelView(channel: Channel): ChannelView {
    if (channel.notifier === LOG_NOTIFIER) return { tone: 'good', label: 'built in', detail: null }
    if (!channel.reachable) {
        return { tone: 'quiet', label: 'no connection', detail: 'Nothing delivers through this channel yet.' }
    }
    if (channel.last_check_at === null) return { tone: 'quiet', label: 'never checked', detail: null }
    return {
        tone: channel.last_check_healthy === true ? 'good' : 'critical',
        label: channel.last_check_healthy === true ? 'checked' : 'failing',
        detail: channel.last_check_detail,
    }
}
