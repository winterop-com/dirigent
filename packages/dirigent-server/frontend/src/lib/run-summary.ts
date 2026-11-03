/**
 * The runs listing grouped by pipeline: what `GET /runs/$summary` answers, and the address the
 * grouped view is kept in.
 *
 * THE FIELD NAMES ARE THE WIRE'S. Every interface mirrors a pydantic model in
 * `dirigent_client.schemas.runs` member for member.
 */

import { apiJson } from '@/lib/api'
import { RUN_STATUSES, type RunStatus } from '@/lib/status'
import { runsLink, type RunFilters } from '@/lib/runs'

/** One run as a pipeline's summary names it. `RecentRun`. */
export interface RecentRun {
    id: string
    status: RunStatus
    created_at: string
}

/** How one pipeline's runs in the window went. `PipelineRuns`. */
export interface PipelineRuns {
    pipeline: string
    name: string | null
    latest: RecentRun
    /** Runs per state; a state with none is left out. */
    counts: Partial<Record<RunStatus, number>>
    /** The most recent runs, oldest first. */
    recent: RecentRun[]
    /** The median duration of the settled runs, or null where none settled. */
    median_duration_ms: number | null
}

/** Each pipeline's runs in a window, the one that ran last first. `RunSummary`. */
export interface RunSummary {
    window: { start: string; end: string }
    pipelines: PipelineRuns[]
}

/** The windows the grouped view offers, each a duration `since` parses. */
export const GROUP_WINDOWS = ['1h', '24h', '7d'] as const

export type GroupWindow = (typeof GROUP_WINDOWS)[number]

/** The window the grouped view opens on. */
export const DEFAULT_GROUP_WINDOW: GroupWindow = '24h'

/** Which view of the runs an address asks for. */
export interface RunsView {
    grouped: boolean
    window: GroupWindow
}

/** The grouped window a duration names, or the default where the grouped view does not offer it. */
export function groupWindowOf(window: string): GroupWindow {
    return (GROUP_WINDOWS as readonly string[]).includes(window)
        ? (window as GroupWindow)
        : DEFAULT_GROUP_WINDOW
}

/** The view an address asks for: `?group=pipeline&window=24h`, a window it does not offer dropped. */
export function viewFromQuery(query: URLSearchParams): RunsView {
    return { grouped: query.get('group') === 'pipeline', window: groupWindowOf(query.get('window') ?? '') }
}

/**
 * The address of the grouped view, carrying the filters it reads.
 *
 * `since` is the flat list's window and has no part here: the grouped view's window is `window`.
 */
export function groupedLink(filters: RunFilters, window: GroupWindow): string {
    const query = new URLSearchParams({ group: 'pipeline', window })
    if (filters.pipeline !== '') query.set('pipeline', filters.pipeline)
    if (filters.status !== '') query.set('status', filters.status)
    for (const tag of filters.tags) query.append('tag', tag)
    return `/runs?${query.toString()}`
}

/** The flat list of one pipeline's runs, over the window its group was read in. */
export function pipelineRunsLink(pipeline: string, window: GroupWindow): string {
    return runsLink({ pipeline, status: '', since: window, tags: [] })
}

/**
 * Where the summary is read from.
 *
 * The status filter asks for the pipelines whose newest run is in that state, which is what a
 * state means of a pipeline rather than of one run.
 */
export function summaryPath(filters: RunFilters, window: GroupWindow): string {
    const query = new URLSearchParams({ since: window })
    if (filters.pipeline !== '') query.set('pipeline', filters.pipeline)
    if (filters.status !== '') query.set('latest', filters.status)
    for (const tag of filters.tags) query.append('tag', tag)
    return `/runs/$summary?${query.toString()}`
}

/** Read each pipeline's runs over a window. */
export function readSummary(filters: RunFilters, window: GroupWindow): Promise<RunSummary> {
    return apiJson<RunSummary>(summaryPath(filters, window))
}

/** The states a pipeline has runs in, in the order the state machine lists them, none at zero. */
export function countsShown(counts: PipelineRuns['counts']): { status: RunStatus; runs: number }[] {
    return RUN_STATUSES.flatMap((status) => {
        const runs = counts[status] ?? 0
        return runs > 0 ? [{ status, runs }] : []
    })
}
