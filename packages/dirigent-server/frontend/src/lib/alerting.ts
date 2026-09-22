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
import { connectionPath, newConnectionPath, type ConnectionOut } from '@/lib/connections'
import { PAGE } from '@/lib/paging'
import type { Importance } from '@/lib/pipelines'

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
    /** The least importance a pipeline must carry before this rule fires; null fires for every one. */
    importance: Importance | null
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
    importance: Importance | null
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

/**
 * The floor a rule fires at, or nothing where it fires whatever the pipeline is worth.
 *
 * It stands beside the scope rather than in a column of its own: almost every rule names no
 * importance at all, so the column would be empty down its whole length.
 */
export function importanceNote(importance: Importance | null): string | null {
    return importance === null ? null : `${importance} and above`
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

/**
 * What may be changed on a rule that already exists. `AlertRuleUpdate`.
 *
 * Every member is optional, and one left out is one the server leaves as it stands -- so a
 * patch carries what changed and nothing else.
 */
export interface AlertRuleUpdate {
    paused?: boolean
    /** The subject, or null to send this rule with the built-in one. */
    template?: string | null
    /** The body, or null to send this rule with none. */
    body?: string | null
}

/** Change what a rule says or whether it delivers. */
export function updateRule(code: string, patch: AlertRuleUpdate): Promise<AlertRuleOut> {
    return apiSend<AlertRuleOut>(`/alert-rules/${encodeURIComponent(code)}`, 'PATCH', patch)
}

/** Hold a rule's deliveries, or let them resume. The rule itself is left as declared. */
export function setRulePaused(code: string, paused: boolean): Promise<AlertRuleOut> {
    return updateRule(code, { paused })
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
 * The channels this instance has, one card each, in the order the strip reads them.
 *
 * Every installed notifier is on the strip, the ones nothing has been set up for included: a
 * channel an alert cannot leave by is what somebody came to this screen to find out.
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
    return orderedChannels(channels)
}

/**
 * What a chip says it is: the credential's code where the channel has one, the notifier's where
 * it has none.
 *
 * A NOTIFIER IS A KIND AND A CONNECTION IS A CHANNEL. Five email credentials are five channels,
 * so a chip carrying the notifier's name five times would say nothing; the glyph carries the
 * kind, and the code says which one this is.
 */
export function channelCode(channel: Channel): string {
    return channel.connection ?? channel.notifier
}

/**
 * Where a chip goes: the credential it delivers through, the door that mints one, or nowhere.
 *
 * The log channel needs nothing and has nothing to open, so nothing is behind its chip.
 */
export function channelLink(channel: Channel): string | null {
    if (channel.connection !== null) return connectionPath(channel.connection)
    if (channel.notifier === LOG_NOTIFIER) return null
    return newConnectionPath(channel.notifier)
}

/**
 * The whole vocabulary of the channel strip: every word a channel can say about itself.
 *
 * `not set up` is a notifier this instance installed and holds no credential for, said in the
 * words somebody would use rather than in the shape of the thing that is missing. The words are
 * the tooltip's; the chip itself carries the dot.
 */
export type ChannelLabel = 'failing' | 'not verified' | 'never checked' | 'checked' | 'ready' | 'not set up'

/** How a channel reads its own health: the dot's colour, the word, and what the check said. */
export interface ChannelView {
    /**
     * The dot, and three colours is all there is: `good` where the channel can deliver,
     * `critical` where its last check failed, `quiet` for everything else.
     */
    tone: 'good' | 'critical' | 'quiet'
    /** The word the tooltip leads with, after the kind. */
    label: ChannelLabel
    /** The sentence under it, which is the check's own where there is one. */
    detail: string | null
}

/**
 * What one channel card says about itself.
 *
 * A CHANNEL NOBODY HAS CHECKED IS NOT A HEALTHY ONE. The states are separate on purpose: a check
 * that failed is the thing this strip exists to surface, a check that has never run says so
 * rather than borrowing the colour of one that passed, and a probe that ran without proving
 * anything -- `last_check_healthy` null behind a `last_check_at` -- is neither. The last three
 * share the grey dot and are told apart by the word.
 */
export function channelView(channel: Channel): ChannelView {
    if (channel.notifier === LOG_NOTIFIER) return { tone: 'good', label: 'ready', detail: null }
    if (!channel.reachable) return { tone: 'quiet', label: 'not set up', detail: null }
    if (channel.last_check_at === null) return { tone: 'quiet', label: 'never checked', detail: null }
    if (channel.last_check_healthy === null) {
        return { tone: 'quiet', label: 'not verified', detail: channel.last_check_detail }
    }
    return {
        tone: channel.last_check_healthy ? 'good' : 'critical',
        label: channel.last_check_healthy ? 'checked' : 'failing',
        detail: channel.last_check_detail,
    }
}

/** The order the dots read in: what delivers, then what broke, then what cannot say. */
const TONES: Readonly<Record<ChannelView['tone'], number>> = { good: 0, critical: 1, quiet: 2 }

/**
 * The strip's order: the dot first, then the notifier, then the connection.
 *
 * A notifier's chips stand together only where their dots agree, so five email credentials read
 * as one run of envelopes unless one of them stopped -- which is the thing the strip is read for.
 */
export function orderedChannels(channels: readonly Channel[]): Channel[] {
    return channels.toSorted((left, right) => {
        const byTone = TONES[channelView(left).tone] - TONES[channelView(right).tone]
        if (byTone !== 0) return byTone
        const byNotifier = left.notifier.localeCompare(right.notifier)
        if (byNotifier !== 0) return byNotifier
        return (left.connection ?? '').localeCompare(right.connection ?? '')
    })
}
