import { beforeEach, describe, expect, test } from 'vitest'

import { checkServer, identityLine, serverStatus, statusOf } from '@/lib/server-status'

function answering(body: unknown, version: unknown = { version: '0.1.0' }): typeof fetch {
    return (async (input: RequestInfo | URL) => {
        const path = String(input)
        return {
            ok: true,
            json: async () => (path.endsWith('/ready') ? body : version),
        } as Response
    }) as typeof fetch
}

/** What `/system/info` says this instance is, for a corner that has to name it. */
function saying(name: string, environment: string) {
    return async () => ({ name, environment })
}

/** An instance that will not say what it is: not signed in, or the read refused. */
const silent = async () => {
    throw new Error('refused')
}

beforeEach(() => {
    serverStatus.set({
        state: 'unknown',
        version: null,
        name: null,
        environment: null,
        checks: [],
        checkedAt: null,
    })
})

describe('what a readiness body means', () => {
    test('the worst status is the state, and the checks come sorted by name', () => {
        const view = statusOf({
            status: 'degraded',
            checks: { storage: { status: 'degraded', detail: 'slow' }, database: { status: 'healthy' } },
        })
        expect(view.state).toBe('degraded')
        expect(view.checks.map((check) => check.name)).toEqual(['database', 'storage'])
        expect(view.checks[1].detail).toBe('slow')
    })

    test('a status the schema does not name is unknown, not a guess', () => {
        expect(statusOf({ status: 'purple' }).state).toBe('unknown')
    })
})

describe('asking the server', () => {
    test('an answered 503 is a state, not offline: the body still carries the checks', async () => {
        await checkServer(
            answering({ status: 'unhealthy', checks: { database: { status: 'unhealthy', detail: 'gone' } } }),
            silent,
        )
        expect(serverStatus.get().state).toBe('unhealthy')
        expect(serverStatus.get().checks[0].detail).toBe('gone')
    })

    test('a failed fetch is offline, and the last known version is kept', async () => {
        await checkServer(answering({ status: 'healthy', checks: {} }), silent)
        expect(serverStatus.get().version).toBe('0.1.0')
        await checkServer(
            (async () => {
                throw new Error('refused')
            }) as unknown as typeof fetch,
            silent,
        )
        expect(serverStatus.get().state).toBe('offline')
        expect(serverStatus.get().version).toBe('0.1.0')
    })

    test('an instance that will not say what it is still gets a working dot', async () => {
        await checkServer(answering({ status: 'healthy', checks: {} }), silent)
        expect(serverStatus.get().state).toBe('healthy')
        expect(serverStatus.get().name).toBeNull()
    })

    test('the name is asked for once and then kept, however often the dot re-asks', async () => {
        let asked = 0
        const info = async () => {
            asked += 1
            return { name: 'dirigent', environment: 'production' }
        }
        await checkServer(answering({ status: 'healthy', checks: {} }), info)
        await checkServer(answering({ status: 'healthy', checks: {} }), info)
        expect(asked).toBe(1)
        expect(serverStatus.get().name).toBe('dirigent')
    })

    test('going offline keeps the name, because the instance is still the one it was', async () => {
        await checkServer(answering({ status: 'healthy', checks: {} }), saying('orders', 'staging'))
        await checkServer(
            (async () => {
                throw new Error('refused')
            }) as unknown as typeof fetch,
            silent,
        )
        expect(serverStatus.get().state).toBe('offline')
        expect(serverStatus.get().name).toBe('orders')
        expect(serverStatus.get().environment).toBe('staging')
    })
})

describe('the line the corner says', () => {
    test('names the instance and the environment it thinks it is in', () => {
        expect(identityLine({ name: 'orders', environment: 'staging' })).toBe('orders · staging')
    })

    test('drops the environment in production, which needs no label', () => {
        expect(identityLine({ name: 'orders', environment: 'production' })).toBe('orders')
    })

    test('is the app own name before anything has been able to ask', () => {
        expect(identityLine({ name: null, environment: null })).toBe('dirigent')
    })

    test('says the name alone when the instance names no environment', () => {
        expect(identityLine({ name: 'orders', environment: null })).toBe('orders')
    })
})

test('a failing version read cannot call an answering instance offline', async () => {
    serverStatus.set({
        state: 'unknown',
        version: null,
        name: null,
        environment: null,
        checks: [],
        checkedAt: null,
    })
    let asked = 0
    const fetcher = (async (path: string) => {
        asked += 1
        if (path === '/health/ready') {
            return { ok: true, json: async () => ({ status: 'healthy', checks: {} }) } as Response
        }
        throw new Error('the restart window')
    }) as (path: string) => Promise<Response>
    await checkServer(fetcher, async () => {
        throw new Error('not signed in')
    })
    expect(serverStatus.get().state).toBe('healthy')
    expect(asked).toBeGreaterThan(1)
})
