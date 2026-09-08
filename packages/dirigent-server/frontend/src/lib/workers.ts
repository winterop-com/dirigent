/**
 * The worker registry, and what one glance at it should say.
 *
 * THE FIELD NAMES ARE THE WIRE'S: `WorkerOut` in `dirigent_client.schemas.system`, member for
 * member. `stale` and `code_matches_server` are the server's own conclusions and are not
 * recomputed here.
 *
 * A TILE STATES THE WORST FACT, NOT THE FIRST ONE. Six workers, one of them running code this
 * server does not have -- the tile that said "5 of 6 answering, worker-a is starting" would be
 * telling the truth and saying nothing. `worstConcern` orders every fact a worker can present
 * and answers the one a person has to know first, and it is a pure function so that ordering is
 * a decision a test makes rather than a judgement a reviewer has to re-make.
 */

import { apiJson, type Page } from '@/lib/api'
import { PAGE } from '@/lib/paging'

/** Where a worker is in its own life. `WorkerStatus` in dirigent_client.enums. */
export type WorkerStatus = 'starting' | 'running' | 'draining' | 'stopped'

/** One node claiming work. `WorkerOut`. */
export interface WorkerOut {
    id: string
    name: string
    hostname: string
    version: string
    status: WorkerStatus
    concurrency: number
    tags: string[]
    plugins: Record<string, unknown>
    catalog_digest: string | null
    /** Whether this worker's block catalog is the one the server has. */
    code_matches_server: boolean
    /** Whether the server has stopped hearing from it. Computed server-side against its own clock. */
    stale: boolean
    created_at: string
    last_seen_at: string
}

/** Where one page of the workers listing is read from. */
export function workersPath(after: string | null, limit: number = PAGE): string {
    const query = new URLSearchParams({ limit: String(limit) })
    if (after !== null) query.set('after', after)
    return `/workers?${query.toString()}`
}

/** Read one page of workers, in name order. */
export function readWorkers(after: string | null): Promise<Page<WorkerOut>> {
    return apiJson<Page<WorkerOut>>(workersPath(after))
}

/**
 * Whether any worker in the registry carries a tag, which is what makes the Tags column worth
 * a column. An instance that never routes by tag would read a column of dashes otherwise.
 */
export function anyTagged(workers: readonly WorkerOut[]): boolean {
    return workers.some((worker) => worker.tags.length > 0)
}

/** Whether a worker is answering: heard from recently, and not shut down. */
export function workerAlive(worker: WorkerOut): boolean {
    return !worker.stale && worker.status !== 'stopped'
}

/** What one worker presents, worst first. `null` is a worker with nothing to report. */
export type Concern = 'silent' | 'mismatched' | 'draining' | 'stopped' | 'starting'

/**
 * The concerns in the order a person needs to hear them.
 *
 * A worker nobody has heard from may be holding a claimed attempt that will never finish, so it
 * is first. One that answers with the wrong catalog is second: it is up, and it will run
 * something other than what this server thinks it will. Draining is capacity leaving now,
 * stopped is capacity already gone and said so, starting is nothing yet.
 */
export const CONCERNS: readonly Concern[] = ['silent', 'mismatched', 'draining', 'stopped', 'starting']

/** What one worker presents, or nothing. */
export function concernOf(worker: WorkerOut): Concern | null {
    if (worker.stale) return 'silent'
    if (!worker.code_matches_server) return 'mismatched'
    if (worker.status === 'draining') return 'draining'
    if (worker.status === 'stopped') return 'stopped'
    if (worker.status === 'starting') return 'starting'
    return null
}

/** One worker's concern as a sentence naming it. */
export function concernNote(worker: WorkerOut, concern: Concern): string {
    return `${worker.name} ${concernSaid(concern)}`
}

/** What is wrong, for a row already headed by the worker it is wrong with. */
export function concernSaid(concern: Concern): string {
    switch (concern) {
        case 'silent':
            return 'has gone quiet'
        case 'mismatched':
            return 'is running a different catalog from this server'
        case 'draining':
            return 'is draining'
        case 'stopped':
            return 'has stopped'
        case 'starting':
            return 'is still starting'
    }
}

/** The one worker whose fact is worst, and which fact it is. Nothing when every worker is well. */
export function worstConcern(workers: readonly WorkerOut[]): { worker: WorkerOut; concern: Concern } | null {
    let worst: { worker: WorkerOut; concern: Concern; rank: number } | null = null
    for (const worker of workers) {
        const concern = concernOf(worker)
        if (concern === null) continue
        const rank = CONCERNS.indexOf(concern)
        if (worst === null || rank < worst.rank) worst = { worker, concern, rank }
    }
    return worst === null ? null : { worker: worst.worker, concern: worst.concern }
}
