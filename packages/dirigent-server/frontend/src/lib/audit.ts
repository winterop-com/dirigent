/**
 * The audit trail: every administrative change, newest first.
 *
 * THE FIELD NAMES ARE THE WIRE'S. `AuditEntryOut` mirrors `dirigent_client.schemas.audit` member
 * for member, and the two enums mirror `AuditAction` and `AuditSubject`.
 *
 * A WINDOW IS A SPAN BACK FROM NOW, AND THE SERVER TAKES AN INSTANT. `since` is computed when the
 * page is asked for, so a listing read again an hour later reads the hour it says it does.
 */

import { apiJson, type Page } from '@/lib/api'
import { LABELS } from '@/lib/labels'
import { PAGE } from '@/lib/paging'

/** What a change did to its subject. `AuditAction`. */
export type AuditAction = keyof typeof LABELS.audit.actions

/** What kind of thing a change was made to. `AuditSubject`. */
export type AuditSubject = keyof typeof LABELS.audit.subjects

/** One administrative change. `AuditEntryOut`. */
export interface AuditEntryOut {
    id: number
    created_at: string
    action: AuditAction
    subject_kind: AuditSubject
    subject_id: string | null
    subject_code: string | null
    /** The code of what the subject belongs to: a schedule's or a source's pipeline, a token's account. */
    parent_code: string | null
    /** The names of the fields an update changed, never their values. */
    fields: string[]
    actor_id: string | null
    actor_username: string | null
    /** The API token the account acted through, or null for a session or the host. */
    actor_token: string | null
    actor_token_prefix: string | null
    actor_label: string
}

/** Every action, in the order a menu offers them. */
export const AUDIT_ACTIONS = Object.keys(LABELS.audit.actions) as AuditAction[]

/** Every subject kind, in the order a menu offers them. */
export const AUDIT_SUBJECTS = Object.keys(LABELS.audit.subjects) as AuditSubject[]

/** The spans back from now the window offers. */
export const AUDIT_WINDOWS = ['1h', '24h', '7d', '30d'] as const

const SPAN_MS: Record<(typeof AUDIT_WINDOWS)[number], number> = {
    '1h': 3_600_000,
    '24h': 86_400_000,
    '7d': 7 * 86_400_000,
    '30d': 30 * 86_400_000,
}

/** What the listing is narrowed by. An empty string is no filter. */
export interface AuditFilters {
    subject_kind: string
    action: string
    actor: string
    subject: string
    window: string
}

export const EVERY_CHANGE: AuditFilters = { subject_kind: '', action: '', actor: '', subject: '', window: '' }

/** Whether any filter is set, which is what decides which empty sentence the listing says. */
export function narrowed(filters: AuditFilters): boolean {
    return Object.values(filters).some((value) => value !== '')
}

/** The instant a window starts at, as the server reads one, or null for no window. */
export function sinceOf(window: string, now: number): string | null {
    const span = SPAN_MS[window as (typeof AUDIT_WINDOWS)[number]]
    return span === undefined ? null : new Date(now - span).toISOString()
}

/** Where one page of the trail is read from. */
export function auditPath(
    filters: AuditFilters,
    after: string | null,
    now: number,
    limit: number = PAGE,
): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (filters.subject_kind !== '') query.set('subject_kind', filters.subject_kind)
    if (filters.action !== '') query.set('action', filters.action)
    if (filters.actor.trim() !== '') query.set('actor', filters.actor.trim())
    if (filters.subject.trim() !== '') query.set('subject', filters.subject.trim())
    const since = sinceOf(filters.window, now)
    if (since !== null) query.set('since', since)
    if (after !== null) query.set('after', after)
    return `/audit?${query.toString()}`
}

/** Read one page of the trail, newest first. */
export function readAudit(filters: AuditFilters, after: string | null): Promise<Page<AuditEntryOut>> {
    return apiJson<Page<AuditEntryOut>>(auditPath(filters, after, Date.now()))
}

/** The subject as it is addressed: `pipeline/schedule`, `account/token`, or the code alone. */
export function subjectOf(entry: AuditEntryOut): string | null {
    if (entry.subject_code === null) return entry.parent_code
    return entry.parent_code === null ? entry.subject_code : `${entry.parent_code}/${entry.subject_code}`
}

/** Who acted: the account, or the host command where none did, and the token it acted through. */
export function actorOf(entry: AuditEntryOut): { who: string; token: string | null } {
    return { who: entry.actor_username ?? entry.actor_label, token: entry.actor_token }
}

/** What the empty listing says. */
export function emptyNote(filters: AuditFilters): string {
    return narrowed(filters) ? LABELS.audit.empty_filtered : LABELS.audit.empty
}
