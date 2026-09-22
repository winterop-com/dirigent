import { afterEach, describe, expect, test, vi } from 'vitest'

import {
    ALERT_EVENTS,
    channelCode,
    channelLink,
    channelsOf,
    channelView,
    deliverySettled,
    EVENT_LABELS,
    importanceNote,
    matchNote,
    notificationsPath,
    orderedChannels,
    ruleLive,
    scopeNote,
    setRulePaused,
    throttleNote,
    updateRule,
    type AlertRuleOut,
    type Channel,
} from '@/lib/alerting'
import { healthOf, type ConnectionOut } from '@/lib/connections'

function aRule(over: Partial<AlertRuleOut> = {}): AlertRuleOut {
    return {
        id: 'r1',
        code: 'page-ops',
        name: null,
        description: null,
        event: 'run_failed',
        scope: 'global',
        pipeline: null,
        importance: null,
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

describe('what an event is called', () => {
    test('every event the wire has is named, in the words a reader is shown', () => {
        expect(ALERT_EVENTS.map((event) => EVENT_LABELS[event])).toEqual([
            'Failed',
            'Completed with errors',
            'Succeeded',
            'Stuck',
        ])
    })

    test('a phrase about a rule says the event in those same words', () => {
        expect(matchNote(aRule())).toBe('Failed — every pipeline')
        expect(matchNote(aRule({ event: 'run_stuck', scope: 'pipeline', pipeline: 'nightly-load' }))).toBe(
            'Stuck — nightly-load',
        )
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

    test('a rule naming a floor says it and every level above it', () => {
        expect(importanceNote('critical')).toBe('critical and above')
        expect(importanceNote('routine')).toBe('routine and above')
    })

    test('a rule naming none says nothing, because it fires whatever a pipeline is worth', () => {
        expect(importanceNote(null)).toBeNull()
        expect(importanceNote(aRule().importance)).toBeNull()
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

/** One instant, so a test that only needs "a check happened" does not spell one out. */
const WHEN = '2026-01-01T00:00:00Z'

describe('the channels an alert can leave by', () => {
    test('log is one channel, needs no credential, and is ready', () => {
        const [channel] = channelsOf(['log'], [])
        expect(channel.connection).toBeNull()
        expect(channel.reachable).toBe(true)
        expect(channelView(channel)).toMatchObject({ tone: 'good', label: 'ready' })
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
        // A credential of another kind is another notifier's channel, and two of one kind whose
        // readings agree stand in code order.
        expect(channels.map((one) => one.connection)).toEqual(['dev-slack', 'ops-slack'])
    })

    test('a notifier nothing has been set up for is a channel nothing can reach, and says so', () => {
        const [channel] = channelsOf(['email'], [])
        expect(channel.reachable).toBe(false)
        expect(channelView(channel)).toMatchObject({ tone: 'quiet', label: 'not set up' })
    })

    test('a probe that proved nothing is neither healthy nor failed', () => {
        const [channel] = channelsOf(
            ['slack'],
            [
                aConnection({
                    last_check_at: '2026-01-01T00:00:00Z',
                    last_check_healthy: null,
                    last_check_detail: 'not verified: posting to the webhook is the only check there is',
                }),
            ],
        )
        expect(channelView(channel)).toEqual({
            tone: 'quiet',
            label: 'not verified',
            detail: 'not verified: posting to the webhook is the only check there is',
        })
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
            label: 'failed',
            detail: 'slack refused the token: invalid_auth',
        })
    })

    test("a channel whose last check passed reads in the connections listing's own word", () => {
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
        expect(channelView(channel)).toMatchObject({ tone: 'good', label: 'healthy' })
    })

    test('a credential says its health in one vocabulary, whichever screen draws it', () => {
        const row = aConnection({
            last_check_at: '2026-01-01T00:00:00Z',
            last_check_healthy: false,
            last_check_detail: 'slack refused the token: invalid_auth',
        })
        const [channel] = channelsOf(['slack'], [row])
        expect(channelView(channel).label).toBe(healthOf(row).label)
        expect(channelView(channel).detail).toBe(healthOf(row).detail)
    })

    test('the strip reads by its dots: what delivers, what broke, what cannot say', () => {
        const channels = channelsOf(
            ['webhook', 'slack', 'log', 'email'],
            [
                aConnection({ id: 'c1', code: 'ops-slack', kind: 'slack' }),
                aConnection({
                    id: 'c2',
                    code: 'dev-slack',
                    kind: 'slack',
                    last_check_at: '2026-01-01T00:00:00Z',
                    last_check_healthy: false,
                    last_check_detail: 'slack refused the token: invalid_auth',
                }),
                aConnection({
                    id: 'c3',
                    code: 'ops-mail',
                    kind: 'email',
                    last_check_at: '2026-01-01T00:00:00Z',
                    last_check_healthy: true,
                    last_check_detail: 'the submission server answered',
                }),
            ],
        )
        expect(channels.map((one) => one.id)).toEqual([
            // Green first, then red, then grey, and inside a colour the notifier's code and then
            // the connection's -- so a notifier's two credentials part where their dots do.
            'email:ops-mail',
            'log',
            'slack:dev-slack',
            'slack:ops-slack',
            'webhook',
        ])
    })

    test('ordering is the same question asked of channels already built', () => {
        const channels = channelsOf(['log', 'webhook'], [])
        expect(orderedChannels(channels).map((one) => one.id)).toEqual(['log', 'webhook'])
    })

    test('three colours and no more: only a failed check is red, only a channel that delivers is green', () => {
        const tones = (channels: readonly Channel[]) => channels.map((one) => channelView(one).tone)
        expect(tones(channelsOf(['log'], []))).toEqual(['good'])
        expect(tones(channelsOf(['webhook'], []))).toEqual(['quiet'])
        expect(tones(channelsOf(['slack'], [aConnection()]))).toEqual(['quiet'])
        const checked = aConnection({ last_check_at: WHEN, last_check_healthy: true })
        expect(tones(channelsOf(['slack'], [checked]))).toEqual(['good'])
        const failed = aConnection({ last_check_at: WHEN, last_check_healthy: false })
        expect(tones(channelsOf(['slack'], [failed]))).toEqual(['critical'])
        const unproved = aConnection({ last_check_at: WHEN, last_check_healthy: null })
        expect(tones(channelsOf(['slack'], [unproved]))).toEqual(['quiet'])
    })

    test('a chip says which credential it is, and falls back to the notifier where there is none', () => {
        const [withOne] = channelsOf(['slack'], [aConnection({ code: 'ops-slack' })])
        expect(channelCode(withOne)).toBe('ops-slack')
        const [without] = channelsOf(['webhook'], [])
        expect(channelCode(without)).toBe('webhook')
    })

    test('a chip opens its credential, a kind with none opens the door, and log opens nothing', () => {
        const [withOne] = channelsOf(['slack'], [aConnection({ code: 'ops slack' })])
        expect(channelLink(withOne)).toBe('/connections/ops%20slack')
        const [without] = channelsOf(['webhook'], [])
        expect(channelLink(without)).toBe('/connections?new=webhook')
        const [log] = channelsOf(['log'], [])
        expect(channelLink(log)).toBeNull()
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
