/**
 * The connection resources, as this bundle reads them.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface here mirrors a pydantic model in
 * `dirigent_client.schemas.connections` member for member.
 *
 * A SECRET IS NEVER A VALUE HERE. The API replaces every secret field with the redaction
 * marker before it answers, so the only thing this bundle can ever know about a stored
 * credential is whether one is set. `settingsSummary` is written so that even a config that
 * did carry a secret value could not put it on screen: the value is never read, only its
 * presence, which is what makes "a secret cannot reach the summary" a test rather than a
 * habit.
 *
 * BLANK KEEPS THE STORED SECRET. `PATCH /connections/{code}` takes the config whole rather
 * than field by field, and a secret field carrying the marker means "keep the one you have".
 * So an edit that left a password box empty sends the marker back, and a field the reader
 * never typed into is absent from the edits rather than present as an empty string -- an
 * empty string is a password somebody chose, and would replace the credential with it.
 */

import { apiJson, apiSend, type JsonMap, type Page } from '@/lib/api'
import { PAGE } from '@/lib/paging'
import { fieldsOf, type FieldDescriptor } from '@/lib/schema-form'

/** What a read shows for a secret field that is set. `REDACTED` in dirigent_core.secrets. */
export const REDACTED = '***'

/** What a secret is drawn as, wherever one is named. Never a value, whatever the config holds. */
export const DOTS = '●●●'

/** A connection as every response shows it: settings visible, secrets redacted. `ConnectionOut`. */
export interface ConnectionOut {
    id: string
    /** The key this connection is addressed by, and the name a step reaches it under. */
    code: string
    /** What to call it on screen, when somebody gave it something to be called. */
    name: string | null
    kind: string
    description: string | null
    config: JsonMap
    /** Which fields the kind declares secret, so a form knows what to render as a password. */
    secret_fields: string[]
    last_check_at: string | null
    last_check_healthy: boolean | null
    last_check_detail: string | null
    created_at: string
    updated_at: string
}

/** The outcome of checking a connection against its external system. `HealthReport`. */
export interface HealthReport {
    healthy: boolean
    detail: string | null
    version: string | null
}

/** One non-block surface in the catalog: a scheme, a notifier, a connection kind. `SurfaceEntry`. */
export interface SurfaceEntry {
    id: string
    plugin: string
    config_schema: JsonMap
    /** Which config fields this surface declares secret, so a form draws them write-only. */
    secret_fields: string[]
}

/**
 * The fields a generated form has a control for: a config schema, minus what it declares secret.
 *
 * A secret is a string in the schema, so a form built from the schema alone would edit a
 * credential -- or the marker standing in for one -- in a plain text box. Every declared secret
 * is left to a write-only password box of its own instead.
 */
export function settingFields(schema: JsonMap | null, secretFields: readonly string[]): FieldDescriptor[] {
    const secret = new Set(secretFields)
    return fieldsOf(schema).filter((field) => !secret.has(field.name))
}

/**
 * The config a new connection is minted with: its settings, and the secrets somebody typed.
 *
 * A SECRET BOX LEFT BLANK SETS NOTHING. An empty string is a password somebody chose, and a
 * connection minted with one holds a credential nobody meant to give it, so an untyped box is
 * absent from the config rather than present as "".
 */
export function mintedConfig(values: JsonMap, secrets: Record<string, string>): JsonMap {
    const config: JsonMap = { ...values }
    for (const [name, typed] of Object.entries(secrets)) {
        if (typed === '') continue
        config[name] = typed
    }
    return config
}

/** The host's merged view of every contribution. `Catalog`, of which one member is read here. */
interface Catalog {
    connection_kinds: SurfaceEntry[]
}

/**
 * Read one page of connections, in code order.
 *
 * The default is the first page, which is what a screen wanting the whole short listing --
 * the editor's connections pane -- asks for; the listing screen passes the cursor it holds.
 */
export function readConnections(after: string | null = null): Promise<Page<ConnectionOut>> {
    const query = new URLSearchParams({ limit: String(PAGE) })
    if (after !== null) query.set('after', after)
    return apiJson<Page<ConnectionOut>>(`/connections?${query.toString()}`)
}

/** Ask a connection's kind whether the external system answers, and record what it said. */
export function checkConnection(code: string): Promise<HealthReport> {
    return apiJson<HealthReport>(`/connections/${encodeURIComponent(code)}/$check`, { method: 'POST' })
}

/** What creating a connection sends. `ConnectionIn`. */
export interface ConnectionIn {
    code: string
    name: string | null
    kind: string
    description: string | null
    config: JsonMap
}

/** Mint a connection of an installed kind. */
export function createConnection(payload: ConnectionIn): Promise<ConnectionOut> {
    return apiSend<ConnectionOut>('/connections', 'POST', payload)
}

/** What editing a connection may change; the kind and the code are fixed once minted. `ConnectionUpdate`. */
export interface ConnectionUpdate {
    name?: string | null
    description?: string | null
    config?: JsonMap
}

/** Send an edit. A member left out of the body is a member the server leaves alone. */
export function updateConnection(code: string, body: ConnectionUpdate): Promise<ConnectionOut> {
    return apiSend<ConnectionOut>(`/connections/${encodeURIComponent(code)}`, 'PATCH', body)
}

/** The connection kinds this instance has installed, which is what a new connection may be. */
export async function readConnectionKinds(): Promise<SurfaceEntry[]> {
    const catalog = await apiJson<Catalog>('/blocks')
    return catalog.connection_kinds
}

/** How many settings the summary line names before it starts counting the rest. */
const SUMMARY_FIELDS = 4

/** How much of one setting's value the summary line carries. */
const VALUE_BUDGET = 28

/**
 * The one line under a connection's title saying what it is pointed at.
 *
 * A SECRET IS DOTS, ALWAYS. Every secret field that holds a credential is rendered as its name
 * and three dots, and the value it holds is never read -- not to test it, not to shorten it,
 * not to decide whether to show it. All that is asked of a secret is whether one is stored, so
 * there is no path through this function that a credential could travel down.
 *
 * A CREDENTIAL IS NEVER COUNTED AWAY. Plain settings are trimmed to a line's worth and the
 * rest are counted, but a secret that is set is always named: whether this connection holds a
 * credential is the one thing about it the listing exists to say. A secret with nothing behind
 * it is not on the line at all -- the form has a box for it, and an empty box says more than a
 * word would.
 */
export function settingsSummary(row: Pick<ConnectionOut, 'config' | 'secret_fields'>): string {
    const secret = new Set(row.secret_fields)
    const settings: string[] = []
    for (const name of Object.keys(row.config)) {
        if (secret.has(name)) continue
        const value = row.config[name]
        if (value === null || value === undefined) continue
        settings.push(`${name}=${short(value)}`)
    }
    const held = row.secret_fields.filter((name) => isSet(row.config[name])).map((name) => `${name} ${DOTS}`)
    const shown = settings.slice(0, SUMMARY_FIELDS)
    const rest = settings.length - shown.length
    const parts = [...shown, ...held, ...(rest > 0 ? [`+${String(rest)} more`] : [])]
    return parts.length === 0 ? 'no settings' : parts.join(' · ')
}

/** Whether a field holds anything at all, which for a secret is the whole of what a read says. */
function isSet(value: unknown): boolean {
    return value !== null && value !== undefined
}

/** One setting's value at a readable length, whatever JSON shape it arrived as. */
function short(value: unknown): string {
    const text = typeof value === 'string' ? value : JSON.stringify(value)
    if (text === undefined) return ''
    return text.length <= VALUE_BUDGET ? text : `${text.slice(0, VALUE_BUDGET - 1)}…`
}

/** Whether a connection answered, refused, or has never been asked. */
export type HealthState = 'healthy' | 'failed' | 'unchecked'

/** How a connection's health reads in the listing. */
export interface HealthView {
    state: HealthState
    /** What the dot is filled with: a semantic alias, or nothing for one never checked. */
    tone: 'good' | 'critical' | null
    /** The words beside the dot. */
    label: string
    /** What the check said when it did not go well, or nothing. */
    detail: string | null
    checkedAt: string | null
}

/** What the health cell draws, from the three fields the row carries about its last check. */
export function healthOf(
    row: Pick<ConnectionOut, 'last_check_at' | 'last_check_healthy' | 'last_check_detail'>,
): HealthView {
    if (row.last_check_at === null || row.last_check_healthy === null) {
        return { state: 'unchecked', tone: null, label: 'never checked', detail: null, checkedAt: null }
    }
    if (row.last_check_healthy) {
        return {
            state: 'healthy',
            tone: 'good',
            label: 'healthy',
            detail: row.last_check_detail,
            checkedAt: row.last_check_at,
        }
    }
    return {
        state: 'failed',
        tone: 'critical',
        label: 'failed',
        detail: row.last_check_detail,
        checkedAt: row.last_check_at,
    }
}

/** What a check has answered, over a set of connections. */
export interface ConnectionsHealth {
    total: number
    healthy: number
    failed: number
    /** How many nothing has ever asked, which is neither of the other two. */
    unchecked: number
}

/** A row this app reads a connection's health off, which is the three fields a check writes. */
export type Checked = Pick<ConnectionOut, 'last_check_at' | 'last_check_healthy' | 'last_check_detail'>

/** How a set of connections came out the last time anything asked each of them. */
export function connectionsHealth(rows: readonly Checked[]): ConnectionsHealth {
    const states = rows.map((row) => healthOf(row).state)
    return {
        total: rows.length,
        healthy: states.filter((state) => state === 'healthy').length,
        failed: states.filter((state) => state === 'failed').length,
        unchecked: states.filter((state) => state === 'unchecked').length,
    }
}

/**
 * The one clause every screen states a set of connections' health in.
 *
 * A CONNECTION NOTHING HAS CHECKED IS NOT AN UNHEALTHY ONE. "0 of 1 healthy" of a credential
 * nobody has asked yet reads as one that answered wrongly, so what has never been asked is said
 * beside the count rather than folded into it. The dashboard, the connections screen and the
 * admin tile all read here, or three screens state three answers to one question.
 *
 * `noun` is the word a sentence about more than connections needs; the screen whose subject is
 * already connections passes none.
 */
export function connectionsNote(rows: readonly Checked[], noun = ''): string | null {
    if (rows.length === 0) return null
    const { total, healthy, unchecked } = connectionsHealth(rows)
    const named = noun === '' ? '' : ` ${noun}`
    const counted = `${String(healthy)} of ${String(total)}${named} healthy`
    if (unchecked === 0) return counted
    return `${counted} · ${String(unchecked)} ${unchecked === 1 ? 'has' : 'have'} never been checked`
}

/**
 * The row a check just answered for, without reading the listing again.
 *
 * `POST /connections/{code}/$check` answers the report and writes the same three fields onto
 * the row it checked, so composing them here and re-reading the listing would say the same
 * thing -- and this way the row somebody is looking at updates rather than moving.
 */
export function withCheck(row: ConnectionOut, report: HealthReport, at: string): ConnectionOut {
    return { ...row, last_check_at: at, last_check_healthy: report.healthy, last_check_detail: report.detail }
}

/**
 * The config a form sends back, from what the read showed and what somebody typed.
 *
 * `edits` carries only the boxes that were typed into. A secret box left blank is absent from
 * it -- never present as an empty string -- so what goes on the wire for that field is what
 * the read showed, which for a stored credential is the marker the server keeps it by.
 */
export function editedConfig(row: Pick<ConnectionOut, 'config'>, edits: Record<string, unknown>): JsonMap {
    return { ...row.config, ...edits }
}

/**
 * The PATCH body one edit sends, or nothing at all when nothing changed.
 *
 * A member left out is a member the server leaves alone, so a name or a description nobody
 * touched is not sent back, and a form with no edits at all sends no request.
 */
export function patchBody(
    row: Pick<ConnectionOut, 'config' | 'name' | 'description'>,
    edits: Record<string, unknown>,
    named: string | null,
    description: string | null,
): ConnectionUpdate | null {
    const body: ConnectionUpdate = {}
    if (named !== row.name) body.name = named
    if (description !== row.description) body.description = description
    if (Object.keys(edits).length > 0) body.config = editedConfig(row, edits)
    return Object.keys(body).length === 0 ? null : body
}
