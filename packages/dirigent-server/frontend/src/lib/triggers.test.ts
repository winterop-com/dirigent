import { describe, expect, test } from 'vitest'

import {
    clockOf,
    deliveryView,
    firingView,
    hookPath,
    nextFireView,
    oneTimeView,
    signing,
    triggerId,
    type DeliveryOut,
    type FiringOut,
    type ScheduleOut,
    type WebhookOut,
} from '@/lib/triggers'

const SCHEDULE: ScheduleOut = {
    id: '11111111-1111-7111-8111-111111111111',
    code: 'nightly',
    name: null,
    description: null,
    kind: 'cron',
    cron: '0 5 * * *',
    interval: null,
    at: null,
    timezone: 'Europe/Oslo',
    params: {},
    priority: null,
    paused: false,
    managed: true,
    trigger_document: null,
    next_fire_at: '2026-03-02T04:00:00Z',
    last_fired_at: '2026-03-01T04:00:00Z',
    created_at: '2026-03-01T00:00:00Z',
}

const WEBHOOK: WebhookOut = {
    id: '22222222-2222-7222-8222-222222222222',
    code: 'upstream-publish',
    name: null,
    description: null,
    token_prefix: 'dgh_abcd',
    params_from_payload: { day: '$.published.date' },
    signed: true,
    active: true,
    managed: true,
    trigger_document: null,
    rate_limit_per_minute: 60,
    priority: null,
    last_delivery_at: '2026-03-01T04:00:00Z',
    created_at: '2026-03-01T00:00:00Z',
}

function firing(over: Partial<FiringOut>): FiringOut {
    return {
        id: 1,
        scheduled_for: '2026-03-01T04:00:00Z',
        created_at: '2026-03-01T04:00:01Z',
        outcome: 'fired',
        misfired: false,
        run_id: null,
        detail: null,
        ...over,
    }
}

function delivery(over: Partial<DeliveryOut>): DeliveryOut {
    return {
        id: 1,
        created_at: '2026-03-01T04:00:00Z',
        outcome: 'accepted',
        run_id: null,
        reason: null,
        mapped_params: null,
        source: null,
        ...over,
    }
}

describe('when a schedule fires next', () => {
    test('is the instant the scheduler computed', () => {
        expect(nextFireView(SCHEDULE)).toEqual({ kind: 'due', at: '2026-03-02T04:00:00Z' })
    })

    // REVERT-PROOF: pausing leaves `next_fire_at` on the row so resuming has somewhere to carry
    // on from, and drawing it would promise a firing the scheduler will not make.
    test('is nothing at all while it is paused, whatever instant the row still carries', () => {
        expect(nextFireView({ ...SCHEDULE, paused: true })).toEqual({ kind: 'paused' })
    })

    // A one-time schedule pauses itself once its moment has gone by, so the flag alone would
    // have a spent clock reading as one somebody stopped.
    test('is nothing when the clock has run out, paused though a spent schedule is', () => {
        expect(nextFireView({ paused: false, next_fire_at: null })).toEqual({ kind: 'none' })
        expect(nextFireView({ paused: true, next_fire_at: null })).toEqual({ kind: 'none' })
    })
})

describe('the moment a one-time schedule names', () => {
    const ONCE = { ...SCHEDULE, kind: 'one_time' as const, cron: null, at: '2026-06-01T09:00:00Z' }

    test('is the instant, unfired, while nothing has fired it', () => {
        expect(oneTimeView({ ...ONCE, last_fired_at: null })).toEqual({
            at: '2026-06-01T09:00:00Z',
            fired: false,
        })
    })

    test('says it fired once it has, which is what the row states instead of a stale future', () => {
        expect(oneTimeView({ ...ONCE, last_fired_at: '2026-06-01T09:00:02Z' })).toEqual({
            at: '2026-06-01T09:00:00Z',
            fired: true,
        })
    })

    // A moment the scheduler has not reached yet is not a firing, however long ago it passed.
    test('is unfired for a moment that has passed with no firing behind it', () => {
        expect(oneTimeView({ at: '2020-01-01T00:00:00Z', last_fired_at: null })).toEqual({
            at: '2020-01-01T00:00:00Z',
            fired: false,
        })
    })

    test('is nothing for a schedule whose clock is not a moment', () => {
        expect(oneTimeView(SCHEDULE)).toBeNull()
    })
})

describe('the one clock a schedule has', () => {
    test('reads a cron expression as the machine string it is', () => {
        expect(clockOf(SCHEDULE)).toEqual({ kind: 'cron', text: '0 5 * * *', mono: true })
    })

    test('reads an interval as the humane duration the API wrote back', () => {
        expect(clockOf({ cron: null, interval: '15m', at: null })).toEqual({
            kind: 'interval',
            text: 'every 15m',
            mono: false,
        })
    })

    test('reads a one-time schedule as the moment it fires', () => {
        expect(clockOf({ cron: null, interval: null, at: '2026-06-01T09:00:00Z' })).toEqual({
            kind: 'at',
            text: '2026-06-01T09:00:00Z',
            mono: false,
        })
    })

    test('takes the clocks in order, so a row carrying two is read as the first of them', () => {
        expect(clockOf({ cron: '0 5 * * *', interval: '15m', at: '2026-06-01T09:00:00Z' }).kind).toBe('cron')
        expect(clockOf({ cron: null, interval: '15m', at: '2026-06-01T09:00:00Z' }).kind).toBe('interval')
    })

    test('says a row with no clock has none rather than drawing an empty cell', () => {
        expect(clockOf({ cron: null, interval: null, at: null })).toEqual({
            kind: 'none',
            text: 'no clock',
            mono: false,
        })
    })
})

describe('what one firing came to', () => {
    test('a firing that started a run carries the run it started', () => {
        const view = firingView(firing({ run_id: 'run-1' }))
        expect(view.tone).toBe('good')
        expect(view.runId).toBe('run-1')
        expect(view.label).toBe('fired')
    })

    test('a misfire is amber and says so, whatever else the outcome was', () => {
        const view = firingView(firing({ misfired: true, detail: 'the scheduler was 40m late' }))
        expect(view.tone).toBe('warn')
        expect(view.label).toBe('fired (misfired)')
        expect(view.detail).toBe('the scheduler was 40m late')
    })

    test('a firing that could not create a run at all is critical, with the reason on it', () => {
        const view = firingView(firing({ outcome: 'failed', detail: 'the pipeline has no version' }))
        expect(view.tone).toBe('critical')
        expect(view.detail).toBe('the pipeline has no version')
    })

    test('a firing the concurrency policy dropped is quiet, because nothing went wrong', () => {
        expect(firingView(firing({ outcome: 'skipped' })).tone).toBe('quiet')
        expect(firingView(firing({ outcome: 'queued' })).tone).toBe('quiet')
        expect(firingView(firing({ outcome: 'replaced' })).tone).toBe('quiet')
    })
})

describe('what one delivery came to', () => {
    test('an accepted delivery carries the run it started', () => {
        const view = deliveryView(delivery({ run_id: 'run-2' }))
        expect(view.tone).toBe('good')
        expect(view.runId).toBe('run-2')
    })

    test('a refusal is critical and carries the reason it was refused with', () => {
        const view = deliveryView(delivery({ outcome: 'rejected', reason: 'signature did not verify' }))
        expect(view.tone).toBe('critical')
        expect(view.reason).toBe('signature did not verify')
        expect(view.runId).toBeNull()
    })

    test('a delivery the concurrency policy dropped is quiet', () => {
        expect(
            deliveryView(delivery({ outcome: 'skipped', reason: 'one run is already in flight' })).tone,
        ).toBe('quiet')
    })
})

describe('what a webhook shows of itself', () => {
    test('shows the prefix and never the rest of the token', () => {
        expect(hookPath(WEBHOOK)).toBe('/hooks/dgh_abcd…')
    })

    test('says whether a delivery has to prove who sent it', () => {
        expect(signing(WEBHOOK)).toBe('HMAC')
        expect(signing({ signed: false })).toBe('unsigned')
    })
})

describe('the rows of both kinds in one listing', () => {
    test('a schedule and a webhook are never the same row', () => {
        expect(triggerId({ kind: 'schedule', pipeline: 'p', schedule: SCHEDULE, latest: null })).toBe(
            `schedule:${SCHEDULE.id}`,
        )
        expect(triggerId({ kind: 'webhook', pipeline: 'p', webhook: WEBHOOK, latest: null })).toBe(
            `webhook:${WEBHOOK.id}`,
        )
    })
})
