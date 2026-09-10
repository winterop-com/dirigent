/**
 * The one way this UI reaches the network.
 *
 * `apiFetch` is the only function in this app that calls `fetch`: every request is
 * same-origin and cookie-credentialed, every path is composed onto the prefix this instance
 * mounted at, and every refusal is read as one problem-document shape.
 *
 * The prefix is read, not written down. `Settings.api_prefix` is configurable, so the server
 * answers `GET /config.json` with the prefix it actually mounted at, and the bundle asks
 * once -- a cached promise, so a hundred components mounting at once make one request
 * between them.
 *
 * A 401 is answered with the login page rather than a refusal card on whichever screen was
 * open. The router is not importable from here, so the shell registers what to do.
 *
 * A few paths are the app's rather than the versioned API's -- the probes under `/health` are
 * mounted at the root and answer before any prefix -- and `rootJson` is how one of those is
 * read. It is here rather than in a caller because this file is the only one that calls
 * `fetch`.
 */

/** Where the server states what this instance is. Outside the versioned API, always at the root. */
export const CONFIG_PATH = '/config.json'

/** A JSON object as the API carries one. `JsonMap` in dirigent_common. */
export type JsonMap = Record<string, unknown>

/** One page of a listing, and the cursor that continues it. Mirrors `dirigent_client.schemas.Page`. */
export interface Page<T> {
    items: T[]
    /** The opaque cursor to pass as `after`, or null at the end. There is no total count. */
    next: string | null
}

/** What this instance is: mirrors the document `dirigent_server.ui` serves. */
export interface AppConfig {
    /** The path the versioned API is mounted at, such as `/api/v1`. */
    api_prefix: string
    version: string
}

/**
 * One refusal, in the shape every error response takes.
 *
 * Mirrors `dirigent_client.schemas.Problem`. RFC 9457 with no `type` member: this server
 * never emits one, so nothing here may key off it.
 */
export interface Problem {
    status: number
    /** The status phrase, such as "Not Found". */
    title: string
    /** One sentence a person can act on. This is what a refusal card shows. */
    detail: string
    /** The individual failures, when the refusal is a list of them rather than one. */
    problems: string[]
    /** The path that was asked for, redacted of any credential it carried. */
    instance: string | null
}

/** A request the server refused, carrying the problem document it refused with. */
export class ApiError extends Error {
    readonly status: number
    readonly problem: Problem

    constructor(problem: Problem) {
        super(problem.detail)
        this.name = 'ApiError'
        this.status = problem.status
        this.problem = problem
    }
}

/**
 * Read a refusal's body as a problem document, or describe what arrived instead.
 *
 * A body that is not a problem document is not a server bug to hide: it is a proxy's error
 * page, a truncated response, or a network failure, and the caller is told which. `title` is
 * synthesised from the status so a refusal card has a heading either way.
 */
export function problemOf(status: number, body: unknown, path: string): Problem {
    const fallback: Problem = {
        status,
        title: status === 0 ? 'No answer' : `HTTP ${String(status)}`,
        detail:
            status === 0
                ? 'This server did not answer. It may be starting, or the connection was lost.'
                : `The server answered ${String(status)} with no problem document.`,
        problems: [],
        instance: path,
    }
    if (body === null || typeof body !== 'object') return fallback
    const candidate = body as Record<string, unknown>
    if (typeof candidate.detail !== 'string' || typeof candidate.title !== 'string') return fallback
    return {
        status: typeof candidate.status === 'number' ? candidate.status : status,
        title: candidate.title,
        detail: candidate.detail,
        problems: Array.isArray(candidate.problems) ? candidate.problems.map(String) : [],
        instance: typeof candidate.instance === 'string' ? candidate.instance : path,
    }
}

let pending: Promise<AppConfig> | null = null

/**
 * What this instance is, read once for the life of the tab.
 *
 * A failed read clears the cached promise, so a reader that retries reaches the network
 * again rather than being handed the same rejection forever.
 */
export function appConfig(): Promise<AppConfig> {
    pending ??= readConfig().catch((error: unknown) => {
        pending = null
        throw error
    })
    return pending
}

/** Forget the cached configuration. Tests, and nothing else, call this. */
export function forgetConfig(): void {
    pending = null
}

async function readConfig(): Promise<AppConfig> {
    const response = await fetch(CONFIG_PATH, { credentials: 'same-origin', headers: { accept: 'application/json' } })
    const body: unknown = await response.json().catch(() => null)
    if (!response.ok) throw new ApiError(problemOf(response.status, body, CONFIG_PATH))
    const candidate = body as Record<string, unknown> | null
    if (candidate === null || typeof candidate.api_prefix !== 'string') {
        throw new ApiError(problemOf(response.status, null, CONFIG_PATH))
    }
    return { api_prefix: candidate.api_prefix, version: String(candidate.version ?? '') }
}

let unauthorized: (() => void) | null = null

/** Say what happens when the server reports there is no session. The shell registers a redirect. */
export function onUnauthorized(handler: (() => void) | null): void {
    unauthorized = handler
}

/**
 * Compose one versioned API path onto the prefix this instance mounted at.
 *
 * The path is written as the OpenAPI document writes it -- `/pipelines`, `/auth/me` -- and
 * this is what puts `/api/v1` in front of it. A caller that passed the prefix itself would
 * get it twice, so the leading slash is required and the prefix is never repeated.
 */
export function apiUrl(prefix: string, path: string): string {
    if (!path.startsWith('/')) throw new Error(`an API path must start with '/': ${path}`)
    return `${prefix}${path}`
}

/**
 * `fetch` against the versioned API, with the session attached and the prefix composed.
 *
 * Refusals are not thrown here: the Response comes back as it arrived, so a caller that
 * cares about a 404 can read it. `apiJson` is the one that throws, and it is what almost
 * every caller wants.
 */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
    const config = await appConfig()
    const headers = new Headers(init.headers)
    if (!headers.has('accept')) headers.set('accept', 'application/json')
    const response = await fetch(apiUrl(config.api_prefix, path), {
        ...init,
        headers,
        credentials: 'same-origin',
    })
    if (response.status === 401) unauthorized?.()
    return response
}

/**
 * One read of the versioned API, parsed, with a refusal raised as an `ApiError`.
 *
 * A 204 answers `undefined`, which is what every write on this API returns.
 */
export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response
    try {
        response = await apiFetch(path, init)
    } catch (error) {
        if (error instanceof ApiError) throw error
        throw new ApiError(problemOf(0, null, path))
    }
    if (response.status === 204) return undefined as T
    const body: unknown = await response.json().catch(() => null)
    if (!response.ok) throw new ApiError(problemOf(response.status, body, path))
    return body as T
}

/**
 * One read of a resource whose content is text rather than JSON.
 *
 * A stored report document is markdown and an artifact answers in the content type it was
 * written as, so the body is taken as text. A refusal is still a problem document, so a body
 * that arrives with an error status is read as one before it is raised.
 */
export async function apiText(path: string, init: RequestInit = {}): Promise<string> {
    const headers = new Headers(init.headers)
    headers.set('accept', 'text/*, */*')
    let response: Response
    try {
        response = await apiFetch(path, { ...init, headers })
    } catch (error) {
        if (error instanceof ApiError) throw error
        throw new ApiError(problemOf(0, null, path))
    }
    const body = await response.text().catch(() => '')
    if (!response.ok) {
        let refusal: unknown = null
        try {
            refusal = JSON.parse(body)
        } catch {
            refusal = null
        }
        throw new ApiError(problemOf(response.status, refusal, path))
    }
    return body
}

/**
 * One read of a path the server mounts outside the versioned API.
 *
 * `/health` and `/health/ready` answer at the root whatever `Settings.api_prefix` is, so they
 * are not composed onto a prefix. The Response comes back as it arrived, because readiness
 * answers 503 carrying the readiness document itself rather than a refusal: a caller that
 * treated that status as an error would throw away the very answer it asked for.
 *
 * It is here rather than in a caller because this file is the only one that calls `fetch`.
 */
export async function rootFetch(path: string): Promise<Response> {
    if (!path.startsWith('/')) throw new Error(`a root path must start with '/': ${path}`)
    try {
        return await fetch(path, { credentials: 'same-origin', headers: { accept: 'application/json' } })
    } catch {
        throw new ApiError(problemOf(0, null, path))
    }
}

/** A write of a JSON body, which is how every mutation on this API is spelled. */
export function apiSend<T>(path: string, method: string, body: unknown): Promise<T> {
    return apiJson<T>(path, {
        method,
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
    })
}
