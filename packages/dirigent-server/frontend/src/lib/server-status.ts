/**
 * How the instance is doing, read the way a load balancer asks.
 *
 * `GET /health/ready` is unauthenticated and answers the worst status across the instance's
 * checks plus each check's own, in one cheap read -- so the corner dot can say degraded, not
 * just alive. A 503 is an answer (the body still carries the checks); only a failed fetch is
 * offline. The store holds the last answer; the button re-asks on focus and on a slow clock.
 *
 * ONE READER OF THE PROBE, AND THIS IS IT. The settings dialog's Server pane shows the same
 * checks and its Recheck button is `checkServer`, because two readers of one probe are two
 * answers that can disagree on the same screen.
 *
 * The fetch goes through `rootFetch`, which is `lib/api`'s -- these paths are mounted at the
 * root rather than on the versioned prefix, and `lib/api` is the only file that calls `fetch`.
 *
 * WHAT THIS INSTANCE IS CALLED IS CACHED HERE TOO, and read once. The corner says the name and
 * the environment beside the dot, because a reader with a staging tab and a production tab open
 * has to be able to tell them apart before they press anything -- and a name that never changes
 * while a process is up is asked for once rather than on every recheck.
 */

import { rootFetch } from '@/lib/api'
import { createStore } from '@/lib/store'
import { readSystemInfo, type SystemInfo } from '@/lib/system'

/** How often the corner dot re-asks while the tab is visible. */
export const RECHECK_INTERVAL_MS = 60_000

export type ServerState = 'unknown' | 'healthy' | 'degraded' | 'unhealthy' | 'offline'

export interface CheckView {
    name: string
    status: string
    detail: string | null
}

export interface ServerStatus {
    state: ServerState
    version: string | null
    /** What this instance calls itself, or null while nothing has been able to ask. */
    name: string | null
    /** Which environment it says it is: `dev`, `staging`, `production`. */
    environment: string | null
    checks: readonly CheckView[]
    checkedAt: number | null
}

export const serverStatus = createStore<ServerStatus>({
    state: 'unknown',
    version: null,
    name: null,
    environment: null,
    checks: [],
    checkedAt: null,
})

/**
 * What the corner says on one line: the instance, and where it thinks it is running.
 *
 * The name alone in production and the name with its environment anywhere else -- a production
 * tab needs no label, and every other tab needs one. Before the read lands there is nothing
 * honest to say but the app's own name.
 */
export function identityLine(status: Pick<ServerStatus, 'name' | 'environment'>): string {
    const name = status.name ?? 'dirigent'
    if (status.environment === null || status.environment === 'production') return name
    return `${name} · ${status.environment}`
}

/** What one readiness body means, independent of who fetched it. */
export function statusOf(body: {
    status?: string
    checks?: Record<string, { status: string; detail?: string | null }>
}): {
    state: ServerState
    checks: CheckView[]
} {
    const checks = Object.entries(body.checks ?? {})
        .map(([name, check]) => ({ name, status: check.status, detail: check.detail ?? null }))
        .toSorted((a, b) => a.name.localeCompare(b.name))
    const state: ServerState =
        body.status === 'healthy' || body.status === 'degraded' || body.status === 'unhealthy'
            ? body.status
            : 'unknown'
    return { state, checks }
}

/** What this instance calls itself, which the corner reads once and then keeps. */
export type InfoReader = () => Promise<Pick<SystemInfo, 'name' | 'environment'>>

/**
 * Ask the instance, and record what came of asking. A failed fetch is offline, kept apart.
 *
 * The name and the environment are asked for only while they are unknown, and a refusal for
 * them leaves them unknown rather than failing the check: the probe is unauthenticated and the
 * info read is not, so a reader who is not signed in yet still gets a dot that works.
 */
export async function checkServer(
    fetcher: (path: string) => Promise<Response> = rootFetch,
    info: InfoReader = readSystemInfo,
): Promise<void> {
    const previous = serverStatus.get()
    // Only the readiness read may say offline. The version and identity reads are
    // enrichment: one of them failing in a restart window must not override an answer
    // the instance just gave.
    let state: ServerState
    let checks: CheckView[]
    try {
        const ready = await fetcher('/health/ready')
        ;({ state, checks } = statusOf((await ready.json()) as Parameters<typeof statusOf>[0]))
    } catch {
        serverStatus.set({
            state: 'offline',
            version: previous.version,
            name: previous.name,
            environment: previous.environment,
            checks: [],
            checkedAt: Date.now(),
        })
        return
    }
    let version = previous.version
    if (version === null) {
        try {
            const health = await fetcher('/health')
            version = health.ok ? (((await health.json()) as { version?: string }).version ?? null) : null
        } catch {
            // The next ask fills it in.
        }
    }
    // Say what is known NOW: the identity read below builds the catalog on a cold instance
    // and can take seconds, and the corner sitting grey behind it helps nobody.
    serverStatus.set({ ...previous, state, version, checks, checkedAt: Date.now() })
    let { name, environment } = previous
    if (name === null) {
        try {
            const said = await info()
            name = said.name
            environment = said.environment
        } catch {
            // Not signed in, or this instance would not say. The corner keeps its own name.
        }
        serverStatus.set({ state, version, name, environment, checks, checkedAt: Date.now() })
    }
}
