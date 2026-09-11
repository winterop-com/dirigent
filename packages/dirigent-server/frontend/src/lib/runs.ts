/**
 * The run resources, as this bundle reads them.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface here mirrors a pydantic model in
 * `dirigent_client.schemas.runs` member for member, so a response is used as it arrived and
 * nothing in this app renames a field the server named. Where a shape is a discriminated one it
 * is discriminated on `kind`.
 *
 * Every call goes through `apiJson`, which is the only fetch in this app; the event stream is
 * `lib/sse`, and the driver that keeps one open is `lib/run-stream`.
 */

import { apiJson, type JsonMap, type Page } from '@/lib/api'
import { PAGE } from '@/lib/paging'
import { tagsFromQuery } from '@/lib/pipelines'
import {
    RUN_STATUSES,
    type AttemptKind,
    type AttemptStatus,
    type LogLevel,
    type RunStatus,
    type TriggerKind,
} from '@/lib/status'

/** How far ahead of the other runs a run's attempts are claimed. `RunPriority`. */
export type RunPriority = 'low' | 'normal' | 'high'

/** What a priority is drawn as, or null where it is drawn as nothing. */
export interface PriorityMark {
    label: string
    className: string
}

/**
 * Decide how a run's priority is drawn beside it.
 *
 * Almost every run is `normal`, so drawing the word on every run would say nothing: only the
 * two answers that are not the default are marked at all.
 */
export function priorityMark(priority: RunPriority): PriorityMark | null {
    if (priority === 'high') return { label: 'high priority', className: 'text-warning' }
    if (priority === 'low') return { label: 'low priority', className: 'text-muted-foreground' }
    return null
}

/** A run as a listing shows it. `RunOut`. */
export interface RunOut {
    id: string
    pipeline: string
    pipeline_version: number
    status: RunStatus
    /** The priority the claim takes this run's attempts at, pinned when it was created. */
    priority: RunPriority
    params: JsonMap
    triggered_by_kind: TriggerKind
    triggered_by_label: string | null
    trace_id: string | null
    error: string | null
    /** The step whose first failed attempt this run holds, when it did not end well. */
    failed_step: string | null
    started_at: string | null
    finished_at: string | null
    /** The start of the logical data interval this run covers, when it carries one. */
    window_start: string | null
    /** The end of that interval, exclusive. Both are set or neither is. */
    window_end: string | null
    created_at: string
}

/** One try of one step, which is the unit a retry addresses. `AttemptOut`. */
export interface AttemptOut {
    id: string
    step_name: string
    block_id: string
    attempt: number
    kind: AttemptKind
    status: AttemptStatus
    run_item_id: string | null
    error: string | null
    error_class: string | null
    output: JsonMap | null
    /** Where the output was written, when it was too large to inline on the artifact. */
    output_uri: string | null
    output_bytes: number | null
    waiting_message: string | null
    waiting_progress: number | null
    /** How many times a probe answered that the work was not done yet. */
    poke_count: number
    next_poll_at: string | null
    /** When the attempt became claimable, which a retry's backoff pushes into the future. */
    available_at: string | null
    /** When the engine gives up, which is the budget this attempt's waiting is spent against. */
    deadline_at: string | null
    /** When a worker last took the attempt up, which on a parked attempt is its last probe. */
    heartbeat_at: string | null
    started_at: string | null
    finished_at: string | null
    /** When the attempt was written down, which is where its queued time is measured from. */
    created_at: string | null
}

/** One attempt state on the run's event stream, with the label its fan-out element goes by. */
export interface AttemptEvent extends AttemptOut {
    item: string | null
    /** Where the element sits in the fan-out, which is the order the elements are listed in. */
    item_index: number | null
}

/** One node of the run's graph. `DagNode`. */
export interface DagNode {
    /** The step's key in the document, which every edge and every attempt references. */
    code: string
    /** The step's human title, when the document gave it one. */
    name: string | null
    block: string
    outcome: string
    depends_on: string[]
    rule: string
    fan_out: boolean
    items_total: number
    items_failed: number
    attempts: number
}

/** The run's graph: its nodes and the edges between them. `DagView`. */
export interface DagView {
    nodes: DagNode[]
    /** `[from, to]` pairs, in the order the nodes were laid out. */
    edges: [string, string][]
}

/** A run, its graph, and how big the grids its sub-resources page are. `RunDetail`. */
export interface RunDetailOut {
    run: RunOut
    dag: DagView
    items_total: number
    attempts_total: number
    /** The worker tags this queued run needs that no live worker carries. */
    waiting_for_workers: string[] | null
}

/**
 * Why a queued run has not started, in one sentence, or nothing when a worker could take it.
 *
 * The tags are the ones no live worker carries, so the sentence names what has to be started
 * rather than what the run asked for.
 */
export function waitingForWorkers(tags: readonly string[] | null | undefined): string | null {
    if (tags === null || tags === undefined || tags.length === 0) return null
    const carried =
        tags.length === 1 ? tags[0] : `${tags.slice(0, -1).join(', ')} and ${tags[tags.length - 1]}`
    return `waiting for a worker carrying ${carried}`
}

/** One product-telemetry entry. `LogEntryOut`. */
export interface LogEntryOut {
    id: number
    run_id: string
    step_name: string | null
    step_attempt_id: string | null
    level: LogLevel
    message: string
    fields: JsonMap | null
    created_at: string
}

/** What one step amounted to. `StepReport`. */
export interface StepReport {
    step: string
    block: string
    outcome: string
    attempts: number
    depends_on: string[]
    warnings: number
    duration_ms: number | null
    error: string | null
}

/** A plain summary of one run. `RunReport`. */
export interface RunReport {
    run_id: string
    pipeline: string
    pipeline_version: number
    status: RunStatus
    triggered_by: string | null
    started_at: string | null
    finished_at: string | null
    duration_ms: number | null
    steps: StepReport[]
    items_total: number
    items_failed: number
    error: string | null
}

/**
 * How many elements a fan-out ran, and how many of them failed where any did.
 *
 * A ZERO IS NOT A FACT. A run with no fan-out has no items to state, and "0 failed" spends a
 * clause saying nothing went wrong -- which the elements' own states already say.
 */
export function itemsNote(total: number, failed: number): string | null {
    if (total === 0) return null
    return failed === 0 ? String(total) : `${String(total)}, ${String(failed)} failed`
}

/** Where the event stream for one run lives, which is the one stream a run's screen opens. */
export function eventsPath(runId: string): string {
    return `/runs/${encodeURIComponent(runId)}/$events`
}

/** Read one run with the graph the UI draws. */
export function readRun(runId: string): Promise<RunDetailOut> {
    return apiJson<RunDetailOut>(`/runs/${encodeURIComponent(runId)}`)
}

/** Read a run's summary, which is where its artifacts and per-step totals come from. */
export function readReport(runId: string): Promise<RunReport> {
    return apiJson<RunReport>(`/runs/${encodeURIComponent(runId)}/$report`)
}

/** How many entries one page of a run's log carries. `MAX_PAGE` on the server, and a 422 above it. */
export const LOG_PAGE = 500

/** Where one page of a run's log is read from, in write order. */
export function logsPath(runId: string, after: string | null, limit: number = LOG_PAGE): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (after !== null) query.set('after', after)
    return `/runs/${encodeURIComponent(runId)}/$logs?${query.toString()}`
}

/**
 * Read one page of a run's whole log.
 *
 * THIS IS NOT WHERE THE SCREEN'S LINES COME FROM. A run's screen reads its lines off the one
 * event stream and holds a tail of them; this is the paged listing behind it, and the only
 * caller is the download, which wants everything the run wrote rather than the tail that fits.
 */
export function readLogs(
    runId: string,
    after: string | null,
    limit: number = LOG_PAGE,
): Promise<Page<LogEntryOut>> {
    return apiJson<Page<LogEntryOut>>(logsPath(runId, after, limit))
}

/** Stop what has not started, and tell the remote about what has. */
export function cancelRun(runId: string): Promise<RunOut> {
    return apiJson<RunOut>(`/runs/${encodeURIComponent(runId)}/$cancel`, { method: 'POST' })
}

/**
 * What the runs listing can be narrowed by.
 *
 * EVERY MEMBER IS A QUERY PARAMETER `GET /runs` TAKES, and the screen offers these four and
 * nothing else. A control for something the server cannot filter would answer over whichever
 * rows happen to have been loaded, which is a different question from the one it appears to ask.
 */
export interface RunFilters {
    /** A pipeline code, spelled exactly, or the empty string for every pipeline. */
    pipeline: string
    /** A `RunStatus`, or the empty string for every state. */
    status: string
    /** A humane window such as `24h`, or the empty string for all of history. */
    since: string
    /**
     * The tags every listed run's pipeline must wear, or none for every pipeline.
     *
     * The question is put to the pipeline the run is of, and asks what it wears now: a run pins
     * its version, never its pipeline's tags.
     */
    tags: string[]
}

/** No filter at all, which is what the screen opens on. */
export const EVERY_RUN: RunFilters = { pipeline: '', status: '', since: '', tags: [] }

/** The windows the screen offers, each one a duration this API's `since` parses. */
export const WINDOWS = ['1h', '24h', '7d', '30d'] as const

/**
 * The address of the runs listing, narrowed the way a link asked for it.
 *
 * A NUMBER ON A DASHBOARD LINKS TO THE ROWS IT COUNTED. A tile that counted the last day's
 * failures and went to the whole listing would answer a click with a different set of rows from
 * the one it stated, so the filters it counted under travel in the address.
 */
export function runsLink(filters: RunFilters): string {
    const query = new URLSearchParams()
    if (filters.pipeline !== '') query.set('pipeline', filters.pipeline)
    if (filters.status !== '') query.set('status', filters.status)
    if (filters.since !== '') query.set('since', filters.since)
    for (const tag of filters.tags) query.append('tag', tag)
    const asked = query.toString()
    return asked === '' ? '/runs' : `/runs?${asked}`
}

/**
 * The filters an address asks for, which is what the listing opens on.
 *
 * ONLY WHAT THE SCREEN'S OWN CONTROLS OFFER. A status the state machine does not have, or a
 * window this API cannot parse, would be a 422 in place of a listing -- and a filter no control
 * can show would leave the bar saying one thing and the rows saying another. Anything else is
 * dropped, so a hand-edited address opens the listing rather than breaking it.
 */
export function filtersFromQuery(query: URLSearchParams): RunFilters {
    const status = query.get('status') ?? ''
    const since = query.get('since') ?? ''
    return {
        pipeline: query.get('pipeline') ?? '',
        status: (RUN_STATUSES as readonly string[]).includes(status) ? status : '',
        since: (WINDOWS as readonly string[]).includes(since) ? since : '',
        tags: tagsFromQuery(query),
    }
}

/** Where one page of the runs listing is read from. */
export function runsPath(filters: RunFilters, after: string | null, limit: number = PAGE): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (filters.pipeline !== '') query.set('pipeline', filters.pipeline)
    if (filters.status !== '') query.set('status', filters.status)
    if (filters.since !== '') query.set('since', filters.since)
    for (const tag of filters.tags) query.append('tag', tag)
    if (after !== null) query.set('after', after)
    return `/runs?${query.toString()}`
}

/** Read one page of runs, newest first. */
export function readRuns(
    filters: RunFilters,
    after: string | null,
    limit: number = PAGE,
): Promise<Page<RunOut>> {
    return apiJson<Page<RunOut>>(runsPath(filters, after, limit))
}

/** What started a run, in the two parts a listing shows it in: the kind, and who or what it was. */
export function triggerSummary(run: RunOut): { kind: string; who: string | null } {
    return { kind: run.triggered_by_kind.replaceAll('_', ' '), who: run.triggered_by_label }
}

/** Whether anything has been asked of the listing at all. */
export function narrowed(filters: RunFilters): boolean {
    return filters.pipeline !== '' || filters.status !== '' || filters.since !== '' || filters.tags.length > 0
}

/**
 * What an empty listing says, which depends on whether anything was asked of it.
 *
 * "No runs yet" in front of somebody who filtered to failures is a lie about the instance, so
 * a narrowed listing says what would widen it instead.
 */
export function emptyNote(filters: RunFilters): string {
    if (narrowed(filters)) return 'No run matches these filters.'
    return 'No runs. A pipeline is run from its own page, or by a schedule or a webhook.'
}
