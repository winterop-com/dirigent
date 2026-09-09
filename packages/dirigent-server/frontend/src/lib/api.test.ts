import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import { ApiError, apiFetch, apiJson, apiUrl, appConfig, forgetConfig, onUnauthorized, problemOf } from '@/lib/api'

/** One canned answer, in the shape `fetch` hands back. */
function answer(status: number, body: unknown, ok = status < 400): Response {
    return {
        ok,
        status,
        json: () => Promise.resolve(body),
    } as unknown as Response
}

const CONFIG = { api_prefix: '/api/v1', version: '0.10.2' }

let calls: { url: string; init: RequestInit }[]

beforeEach(() => {
    forgetConfig()
    onUnauthorized(null)
    calls = []
})

afterEach(() => {
    vi.unstubAllGlobals()
})

/** Stub `fetch`, answering the configuration document and then one canned answer per call. */
function stubFetch(...answers: Response[]): void {
    let next = 0
    vi.stubGlobal('fetch', (url: string, init: RequestInit = {}) => {
        calls.push({ url, init })
        if (url === '/config.json') return Promise.resolve(answer(200, CONFIG))
        const response = answers[next]
        next += 1
        return Promise.resolve(response ?? answer(500, null))
    })
}

describe('apiUrl', () => {
    test('composes a path onto the prefix this instance mounted at', () => {
        expect(apiUrl('/api/v1', '/pipelines')).toBe('/api/v1/pipelines')
    })

    test('a configured prefix is honoured rather than assumed', () => {
        expect(apiUrl('/orchestrator/v2', '/auth/me')).toBe('/orchestrator/v2/auth/me')
    })

    test('a path that does not start with a slash is a programming error, refused here', () => {
        expect(() => apiUrl('/api/v1', 'pipelines')).toThrow("must start with '/'")
    })
})

describe('the configuration document', () => {
    test('is read once however many callers ask', async () => {
        stubFetch(answer(200, { items: [] }), answer(200, { items: [] }))
        await Promise.all([apiJson('/pipelines'), apiJson('/runs')])
        expect(calls.filter((call) => call.url === '/config.json')).toHaveLength(1)
    })

    test('a failed read is not cached, so a retry reaches the network again', async () => {
        vi.stubGlobal('fetch', (url: string) => {
            calls.push({ url, init: {} })
            return Promise.resolve(answer(503, null, false))
        })
        await expect(appConfig()).rejects.toBeInstanceOf(ApiError)
        await expect(appConfig()).rejects.toBeInstanceOf(ApiError)
        expect(calls).toHaveLength(2)
    })
})

describe('apiFetch', () => {
    test('prefixes every path with the prefix the server reported', async () => {
        stubFetch(answer(200, { items: [] }))
        await apiFetch('/pipelines')
        expect(calls.at(-1)?.url).toBe('/api/v1/pipelines')
    })

    test('sends the session cookie, because that is the only credential this bundle has', async () => {
        stubFetch(answer(200, {}))
        await apiFetch('/auth/me')
        expect(calls.at(-1)?.init.credentials).toBe('same-origin')
    })

    test('a refusal for want of a session is the shell to answer, not the caller', async () => {
        stubFetch(answer(401, { status: 401, title: 'Unauthorized', detail: 'no session' }, false))
        const seen = vi.fn()
        onUnauthorized(seen)
        await apiFetch('/auth/me')
        expect(seen).toHaveBeenCalledOnce()
    })
})

describe('a refusal', () => {
    test('arrives as the problem document the server wrote', async () => {
        stubFetch(
            answer(
                422,
                {
                    status: 422,
                    title: 'Unprocessable Content',
                    detail: 'body.steps.0.block_id: no such block',
                    problems: ['body.steps.0.block_id: no such block'],
                    instance: '/api/v1/pipelines/$apply',
                },
                false,
            ),
        )
        const failure = await apiJson('/pipelines/$apply', { method: 'POST' }).catch((error: unknown) => error)
        expect(failure).toBeInstanceOf(ApiError)
        const error = failure as ApiError
        expect(error.status).toBe(422)
        expect(error.problem.detail).toBe('body.steps.0.block_id: no such block')
        expect(error.problem.problems).toEqual(['body.steps.0.block_id: no such block'])
    })

    test('that is not a problem document says what arrived instead of inventing a detail', () => {
        const problem = problemOf(502, '<html>bad gateway</html>', '/api/v1/runs')
        expect(problem.status).toBe(502)
        expect(problem.detail).toContain('no problem document')
        expect(problem.instance).toBe('/api/v1/runs')
    })

    test('from a server that did not answer at all is distinguishable from one that refused', async () => {
        vi.stubGlobal('fetch', (url: string) => {
            if (url === '/config.json') return Promise.resolve(answer(200, CONFIG))
            return Promise.reject(new TypeError('network error'))
        })
        const failure = await apiJson('/runs').catch((error: unknown) => error)
        expect((failure as ApiError).status).toBe(0)
        expect((failure as ApiError).problem.title).toBe('No answer')
    })
})

describe('apiJson', () => {
    test('answers undefined for a 204, which is what every write on this API returns', async () => {
        stubFetch(answer(204, null))
        await expect(apiJson('/auth/logout', { method: 'POST' })).resolves.toBeUndefined()
    })
})
