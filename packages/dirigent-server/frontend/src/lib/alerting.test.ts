import { afterEach, describe, expect, test, vi } from 'vitest'

import {
    channelsOf,
    channelView,
    deliverySettled,
    notificationsPath,
    ruleLive,
    scopeNote,
    setRulePaused,
    throttleNote,
    updateRule,
    type AlertRuleOut,
} from '@/lib/alerting'
import type { ConnectionOut } from '@/lib/connections'

function aRule(over: Partial<AlertRuleOut> = {}): AlertRuleOut {
    return {
        id: 'r1',
        code: 'page-ops',
        name: null,
        description: null,
        event: 'run_failed',
        scope: 'global',
        pipeline: null,
        notifier: 'log',
        connection: null,
        template: null,
        body: null,
        throttle: '0s',
        active: true,
        paused: false,
        last_sent_at: null,
        created_at: '2026-01-01T00:00:00Z',
        ...over,
    }
}

function aConnection(over: Partial<ConnectionOut> = {}): ConnectionOut {
    return {
        id: 'c1',
        code: 'ops-slack',
        name: null,
        kind: 'slack',
        description: null,
        config: {},
        secret_fields: [],
        last_check_at: null,
        last_check_healthy: null,
        last_check_detail: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...over,
    }
}

describe('what the throttle column says', () => {
    test('says a rule with no window has none rather than a duration of nothing', () => {
        expect(throttleNote('0s')).toBe('none')
    })

    test('says a window it has the way the document spells it', () => {
        expect(throttleNote('5m')).toBe('5m')
        expect(throttleNote('1h30m')).toBe('1h30m')
    })
})

describe('what a rule watches', () => {
    test('a global rule watches every pipeline', () => {
        expect(scopeNote(aRule())).toBe('every pipeline')
    })

    test('a scoped rule names the pipeline it watches', () => {
        expect(scopeNote(aRule({ scope: 'pipeline', pipeline: 'nightly-load' }))).toBe('nightly-load')
    })

    test('a scope that names no pipeline still reads as every one rather than as nothing', () => {
        expect(scopeNote(aRule({ scope: 'pipeline', pipeline: null }))).toBe('every pipeline')
    })
})

describe('whether a rule is delivering', () => {
    test('a declared, unpaused rule is live', () => {
        expect(ruleLive(aRule())).toBe(true)
    })

    test('a paused rule is not, however it was declared', () => {
        expect(ruleLive(aRule({ paused: true }))).toBe(false)
    })

    test('an inactive rule is not either', () => {
        expect(ruleLive(aRule({ active: false }))).toBe(false)
    })
})

describe('when a delivery stops moving', () => {
    test('sent and failed are the two nothing moves again', () => {
        expect(deliverySettled('sent')).toBe(true)
        expect(deliverySettled('failed')).toBe(true)
    })

    test('a queued or in-flight row is still moving', () => {
        expect(deliverySettled('pending')).toBe(false)
        expect(deliverySettled('sending')).toBe(false)
    })
})

describe('where the notifications listing is read from', () => {
    test('a filter nobody set is absent from the query rather than empty in it', () => {
        expect(notificationsPath({ status: '', notifier: '' }, null, 50)).toBe('/notifications?limit=50')
    })

    test('a filter that was set narrows the server rather than the screen', () => {
        expect(notificationsPath({ status: 'failed', notifier: 'slack' }, null, 50)).toBe(
            '/notifications?limit=50&status=failed&notifier=slack',
        )
    })

    test('the cursor rides beside the filters', () => {
        expect(notificationsPath({ status: 'sent', notifier: '' }, 'abc', 50)).toBe(
            '/notifications?limit=50&status=sent&after=abc',
        )
    })
})

describe('the channels an alert can leave by', () => {
    test('log is one channel and needs no credential', () => {
        const [channel] = channelsOf(['log'], [])
        expect(channel.connection).toBeNull()
        expect(channel.reachable).toBe(true)
        expect(channelView(channel)).toMatchObject({ tone: 'good', label: 'built in' })
    })

    test('a notifier is one channel per connection of its own kind', () => {
        const channels = channelsOf(
            ['slack'],
            [
                aConnection({ code: 'ops-slack' }),
                aConnection({ id: 'c2', code: 'dev-slack' }),
                aConnection({ id: 'c3', code: 'ops-mail', kind: 'email' }),
            ],
        )
        expect(channels.map((one) => one.connection)).toEqual(['ops-slack', 'dev-slack'])
    })

    test('a notifier with no connection is a channel nothing can reach, and says so', () => {
        const [channel] = channelsOf(['email'], [])
        expect(channel.reachable).toBe(false)
        expect(channelView(channel)).toMatchObject({ tone: 'quiet', label: 'no connection' })
    })

    test('a channel nobody has checked is not a healthy one', () => {
        const [channel] = channelsOf(['slack'], [aConnection()])
        expect(channelView(channel)).toMatchObject({ tone: 'quiet', label: 'never checked' })
    })

    test('a channel whose last check failed carries the sentence it failed with', () => {
        const [channel] = channelsOf(
            ['slack'],
            [
                aConnection({
                    last_check_at: '2026-01-01T00:00:00Z',
                    last_check_healthy: false,
                    last_check_detail: 'slack refused the token: invalid_auth',
                }),
            ],
        )
        expect(channelView(channel)).toEqual({
            tone: 'critical',
            label: 'failing',
            detail: 'slack refused the token: invalid_auth',
        })
    })

    test('a channel whose last check passed reads as checked', () => {
        const [channel] = channelsOf(
            ['slack'],
            [
                aConnection({
                    last_check_at: '2026-01-01T00:00:00Z',
                    last_check_healthy: true,
                    last_check_detail: 'ok',
                }),
            ],
        )
        expect(channelView(channel)).toMatchObject({ tone: 'good', label: 'checked' })
    })
})

describe('what a patch of a rule sends', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    /** Stub `fetch`, answering the configuration document and then the patched rule. */
    function stubFetch(): { url: string; init: RequestInit }[] {
        const calls: { url: string; init: RequestInit }[] = []
        vi.stubGlobal('fetch', (url: string, init: RequestInit = {}) => {
            calls.push({ url, init })
            const body = url === '/config.json' ? { api_prefix: '/api/v1', version: '0.13.0' } : aRule()
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) } as Response)
        })
        return calls
    }

    test('only what changed rides on the patch, and the rule is addressed by its code', async () => {
        const calls = stubFetch()
        await updateRule('page ops', { body: 'Run {{ run.status }}' })
        const patch = calls[calls.length - 1]
        expect(patch.url).toBe('/api/v1/alert-rules/page%20ops')
        expect(patch.init.method).toBe('PATCH')
        expect(patch.init.body).toBe(JSON.stringify({ body: 'Run {{ run.status }}' }))
    })

    test('a template taken off the rule is sent as null rather than left out', async () => {
        const calls = stubFetch()
        await updateRule('page-ops', { template: null, body: null })
        expect(calls[calls.length - 1].init.body).toBe(JSON.stringify({ template: null, body: null }))
    })

    test('pausing is the same patch, carrying nothing the rule says', async () => {
        const calls = stubFetch()
        await setRulePaused('page-ops', true)
        expect(calls[calls.length - 1].init.body).toBe(JSON.stringify({ paused: true }))
    })
})
