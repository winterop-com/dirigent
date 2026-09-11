import { describe, expect, test } from 'vitest'

import type { Page } from '@/lib/api'
import type { ConnectionOut } from '@/lib/connections'
import {
    healthNote,
    healthRows,
    chartSummary,
    CHART_HOURS,
    hourlyRuns,
    hourOf,
    hourStart,
    liveRuns,
    nextFires,
    partOf,
    statTiles,
    stackOf,
    tallest,
    toneOf,
    type PipelineSchedule,
} from '@/lib/home'
import type { RunOut } from '@/lib/runs'
import type { RunStatus } from '@/lib/status'
import type { ScheduleOut } from '@/lib/triggers'
import type { WorkerOut } from '@/lib/workers'

function run(status: RunStatus, created: string, id = status + created): RunOut {
    return {
        id,
        pipeline: 'nightly',
        pipeline_version: 1,
        priority: 'normal',
        status,
        params: {},
        triggered_by_kind: 'schedule',
        triggered_by_label: null,
        trace_id: null,
        error: null,
        failed_step: null,
        started_at: created,
        finished_at: null,
        window_start: null,
        window_end: null,
        created_at: created,
    }
}

function schedule(code: string, over: Partial<ScheduleOut> = {}): PipelineSchedule {
    return {
        pipeline: 'nightly',
        schedule: {
            id: code,
            code,
            name: null,
            description: null,
            kind: 'cron',
            cron: '0 * * * *',
            interval: null,
            at: null,
            timezone: 'UTC',
            params: {},
            priority: null,
            paused: false,
            managed: false,
            trigger_document: null,
            next_fire_at: '2026-01-01T01:00:00Z',
            last_fired_at: null,
            created_at: '2026-01-01T00:00:00Z',
            ...over,
        },
    }
}

/** One page of a listing that has been read to the end. */
function whole<T>(items: T[]): Page<T> {
    return { items, next: null }
}

/** One page of a listing there is more of. */
function truncated<T>(items: T[]): Page<T> {
    return { items, next: 'cursor' }
}

function worker(name: string, over: Partial<WorkerOut> = {}): WorkerOut {
    return {
        id: name,
        name,
        hostname: `${name}.local`,
        version: '1.0.0',
        status: 'running',
        concurrency: 4,
        tags: [],
        plugins: {},
        catalog_digest: 'abc',
        code_matches_server: true,
        stale: false,
        created_at: '2026-01-01T00:00:00Z',
        last_seen_at: '2026-01-01T00:00:00Z',
        ...over,
    }
}

function connection(code: string, healthy: boolean | null, detail: string | null = null): ConnectionOut {
    return {
        id: code,
        code,
        name: null,
        kind: 'http',
        description: null,
        config: {},
        secret_fields: [],
        last_check_at: healthy === null ? null : '2026-01-01T00:00:00Z',
        last_check_healthy: healthy,
        last_check_detail: detail,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

/** The tile a slot holds, by the id the row keys it under. */
function tileOf(slots: ReturnType<typeof statTiles>, id: string) {
    const found = slots.find((slot) => slot.id === id)
    expect(found).toBeDefined()
    return found?.tile ?? null
}

describe('what is running or waiting', () => {
    test('holds both states in one list', () => {
        const rows = liveRuns(
            [run('running', '2026-01-01T02:00:00Z')],
            [run('queued', '2026-01-01T01:00:00Z')],
        )
        expect(rows.map((row) => row.status)).toEqual(['running', 'queued'])
    })

    test('is newest first, whichever listing a row came from', () => {
        const rows = liveRuns(
            [run('running', '2026-01-01T01:00:00Z', 'old')],
            [run('queued', '2026-01-01T05:00:00Z', 'new')],
        )
        expect(rows.map((row) => row.id)).toEqual(['new', 'old'])
    })

    test('stops at the rows the screen has space for', () => {
        const many = Array.from({ length: 9 }, (_, index) =>
            run('running', `2026-01-0${String(index + 1)}T00:00:00Z`),
        )
        expect(liveRuns(many, [], 3)).toHaveLength(3)
    })

    test('is nothing at all when nothing is going, rather than a row saying so', () => {
        expect(liveRuns([], [])).toEqual([])
    })
})

describe('the firings still ahead', () => {
    test('are soonest first', () => {
        const rows = nextFires([
            schedule('late', { next_fire_at: '2026-01-01T09:00:00Z' }),
            schedule('soon', { next_fire_at: '2026-01-01T01:00:00Z' }),
        ])
        expect(rows.map((row) => row.schedule.code)).toEqual(['soon', 'late'])
    })

    // REVERT-PROOF. Read `next_fire_at` without asking `nextFireView` and this fails: a paused
    // schedule keeps the instant it would have fired at, and listing it promises a firing the
    // scheduler will not make.
    test('skip a paused schedule, which keeps a computed instant it will not fire at', () => {
        const rows = nextFires([schedule('nightly', { paused: true })])
        expect(rows).toEqual([])
    })

    test('skip a schedule whose clock names no further moment', () => {
        expect(nextFires([schedule('spent', { next_fire_at: null })])).toEqual([])
    })

    test('carry the pipeline the schedule hangs off, which is the address it is reached at', () => {
        const [row] = nextFires([schedule('hourly')])
        expect(row.pipeline).toBe('nightly')
        expect(row.at).toBe('2026-01-01T01:00:00Z')
    })

    test('stop at the rows the screen has space for', () => {
        const many = Array.from({ length: 9 }, (_, index) =>
            schedule(`s${String(index)}`, { next_fire_at: `2026-01-0${String(index + 1)}T00:00:00Z` }),
        )
        expect(nextFires(many, 4)).toHaveLength(4)
    })
})

describe('a count taken from part of a page', () => {
    test('is the number when the page held the whole listing', () => {
        expect(partOf(3, whole([1, 2, 3, 4]))).toBe('3')
    })

    test('is marked when it was taken from a page there is more of', () => {
        expect(partOf(3, truncated([1, 2, 3, 4]))).toBe('3+')
    })
})

describe('how loudly a count is drawn', () => {
    test('is the tone the tile asked for when there is something to count', () => {
        expect(toneOf(2, 'critical')).toBe('critical')
    })

    // REVERT-PROOF. A zero drawn in the colour of the thing it counts says an instance has
    // failures when what it has is none.
    test('is neutral at zero, whatever the tile is counting', () => {
        expect(toneOf(0, 'critical')).toBe('neutral')
        expect(toneOf(0, 'good')).toBe('neutral')
    })
})

describe('the six numbers the screen opens with', () => {
    const day = whole([
        run('succeeded', '2026-03-04T10:00:00Z', 'a'),
        run('succeeded', '2026-03-04T10:05:00Z', 'b'),
        run('failed', '2026-03-04T10:10:00Z', 'c'),
        run('completed_with_errors', '2026-03-04T10:20:00Z', 'd'),
        run('running', '2026-03-04T11:00:00Z', 'e'),
    ])

    test('are six slots in the order the row draws them', () => {
        expect(statTiles(null, null, null).map((slot) => slot.id)).toEqual([
            'runs',
            'succeeded',
            'failed',
            'completed_with_errors',
            'running',
            'queued',
        ])
    })

    test('hold nothing at all until the read behind them lands', () => {
        expect(statTiles(null, null, null).every((slot) => slot.tile === null)).toBe(true)
    })

    test('count the window out of the one page that was read', () => {
        const slots = statTiles(day, null, null)
        expect(tileOf(slots, 'runs')?.value).toBe('5')
        expect(tileOf(slots, 'succeeded')?.value).toBe('2')
        expect(tileOf(slots, 'failed')?.value).toBe('1')
        expect(tileOf(slots, 'completed_with_errors')?.value).toBe('1')
    })

    test('count what is going out of the unwindowed reads, not out of the window', () => {
        const slots = statTiles(day, whole([run('running', '2026-03-01T00:00:00Z')]), whole([]))
        expect(tileOf(slots, 'running')?.value).toBe('1')
        expect(tileOf(slots, 'queued')?.value).toBe('0')
    })

    test('mark every count taken from a page there is more of', () => {
        const slots = statTiles(truncated(day.items), null, null)
        expect(tileOf(slots, 'runs')?.value).toBe('5+')
        expect(tileOf(slots, 'succeeded')?.value).toBe('2+')
    })

    // REVERT-PROOF. A tile that counted a window and linked to the whole listing would answer a
    // click with a different set of rows from the one it just stated.
    test('link to the rows they counted, window and all', () => {
        const slots = statTiles(day, whole([]), whole([]))
        expect(tileOf(slots, 'runs')?.to).toBe('/runs?since=24h')
        expect(tileOf(slots, 'failed')?.to).toBe('/runs?status=failed&since=24h')
        expect(tileOf(slots, 'running')?.to).toBe('/runs?status=running')
    })

    test('are drawn in their own tone where there is something to count and neutral where not', () => {
        const slots = statTiles(day, whole([]), whole([]))
        expect(tileOf(slots, 'failed')?.tone).toBe('critical')
        expect(tileOf(slots, 'completed_with_errors')?.tone).toBe('warning')
        expect(tileOf(slots, 'succeeded')?.tone).toBe('good')
        expect(tileOf(slots, 'running')?.tone).toBe('neutral')
    })

    test('say nothing under a number that has nothing to add to its own label', () => {
        const slots = statTiles(day, whole([]), whole([run('queued', '2026-03-04T11:30:00Z')]))
        expect(tileOf(slots, 'succeeded')?.note).toBe('')
        expect(tileOf(slots, 'queued')?.note).toBe('Waiting for a worker.')
        expect(tileOf(slots, 'running')?.note).toBe('')
    })
})

describe('the hour an instant falls in', () => {
    const NOON = Date.parse('2026-03-04T12:34:56Z')

    test('is the hour of UTC when that is the clock being read against', () => {
        expect(hourStart(NOON, 0)).toBe(Date.parse('2026-03-04T12:00:00Z'))
        expect(hourOf(NOON, 0)).toBe(12)
    })

    test('moves with the offset, so an hour is an hour of the clock being read against', () => {
        expect(hourStart(NOON, 60)).toBe(Date.parse('2026-03-04T12:00:00Z'))
        expect(hourOf(NOON, 60)).toBe(13)
        expect(hourOf(NOON, -480)).toBe(4)
    })

    // A zone half an hour off the hour puts its hour boundaries at half past UTC's, and a
    // boundary computed from the zone name alone would put them on the hour.
    test('is half past the hour of UTC in a zone that is half an hour off it', () => {
        expect(hourStart(NOON, 330)).toBe(Date.parse('2026-03-04T12:30:00Z'))
        expect(hourOf(NOON, 330)).toBe(18)
    })

    test('is the hour it is already at when an instant sits exactly on a boundary', () => {
        const onTheHour = Date.parse('2026-03-04T12:00:00Z')
        expect(hourStart(onTheHour, 0)).toBe(onTheHour)
    })

    test('wraps rather than running negative when an offset crosses midnight', () => {
        expect(hourOf(Date.parse('2026-03-04T00:30:00Z'), -120)).toBe(22)
        expect(hourOf(Date.parse('2026-03-04T23:30:00Z'), 120)).toBe(1)
    })
})

describe('the last day of runs, by the hour', () => {
    const NOW = new Date('2026-03-04T12:34:00Z')

    test('is one bucket an hour, ending in the hour that is going on now', () => {
        const buckets = hourlyRuns([], NOW, 0)
        expect(buckets).toHaveLength(CHART_HOURS)
        expect(buckets[23].start).toBe(Date.parse('2026-03-04T12:00:00Z'))
        expect(buckets[0].start).toBe(Date.parse('2026-03-03T13:00:00Z'))
        expect(buckets[23].hour).toBe(12)
    })

    test('counts a run into the hour it was created in, by outcome', () => {
        const buckets = hourlyRuns(
            [
                run('succeeded', '2026-03-04T10:05:00Z', 'a'),
                run('succeeded', '2026-03-04T10:45:00Z', 'b'),
                run('failed', '2026-03-04T10:50:00Z', 'c'),
                run('completed_with_errors', '2026-03-04T11:10:00Z', 'd'),
            ],
            NOW,
            0,
        )
        expect(buckets[21]).toMatchObject({ succeeded: 2, failed: 1, withErrors: 0, total: 3 })
        expect(buckets[22]).toMatchObject({ succeeded: 0, failed: 0, withErrors: 1, total: 1 })
    })

    test('counts a run that has not settled in the total and in no band', () => {
        const buckets = hourlyRuns([run('running', '2026-03-04T12:01:00Z')], NOW, 0)
        expect(buckets[23]).toMatchObject({ total: 1, succeeded: 0, failed: 0, withErrors: 0 })
        expect(stackOf(buckets[23])).toBe(0)
    })

    test('puts a run created exactly on a boundary in the hour that boundary begins', () => {
        const buckets = hourlyRuns(
            [
                run('succeeded', '2026-03-04T11:00:00.000Z', 'on'),
                run('failed', '2026-03-04T10:59:59.999Z', 'before'),
            ],
            NOW,
            0,
        )
        expect(buckets[22].succeeded).toBe(1)
        expect(buckets[21].failed).toBe(1)
    })

    test('leaves an hour nothing ran in as a bucket at zero rather than as a gap', () => {
        const buckets = hourlyRuns([run('succeeded', '2026-03-04T12:01:00Z')], NOW, 0)
        expect(buckets.filter((bucket) => bucket.total === 0)).toHaveLength(23)
        const starts = buckets.map((bucket) => bucket.start)
        expect(starts).toEqual(starts.toSorted((left, right) => left - right))
    })

    test('drops a run older than the window and one that has not happened yet', () => {
        const buckets = hourlyRuns(
            [
                run('succeeded', '2026-03-03T12:59:00Z', 'old'),
                run('succeeded', '2026-03-04T13:00:00Z', 'ahead'),
            ],
            NOW,
            0,
        )
        expect(buckets.reduce((sum, bucket) => sum + bucket.total, 0)).toBe(0)
    })

    // REVERT-PROOF against bucketing in UTC whatever the reader is reading against: one instant
    // falls in two different hours on two clocks, and the boundaries move with them.
    test('buckets against the clock it was given rather than against UTC', () => {
        const runs = [run('succeeded', '2026-03-04T12:20:00Z')]
        const utc = hourlyRuns(runs, NOW, 0)
        const ahead = hourlyRuns(runs, NOW, 330)
        expect(utc[23].hour).toBe(12)
        expect(ahead[23].hour).toBe(18)
        expect(ahead[23].start).toBe(Date.parse('2026-03-04T12:30:00Z'))
        expect(ahead[22].succeeded).toBe(1)
    })

    test('the tallest stack is what every bar is a fraction of, and it counts three outcomes', () => {
        const buckets = hourlyRuns(
            [
                run('succeeded', '2026-03-04T12:01:00Z', 'a'),
                run('failed', '2026-03-04T12:02:00Z', 'b'),
                run('running', '2026-03-04T12:03:00Z', 'c'),
            ],
            NOW,
            0,
        )
        expect(tallest(buckets)).toBe(2)
    })

    test('is nothing at all to say when nothing ran', () => {
        expect(chartSummary(hourlyRuns([], NOW, 0))).toBe('No run was started in the last 24 hours.')
    })

    test('says what it drew, for a reader who is hearing it rather than seeing it', () => {
        const summary = chartSummary(
            hourlyRuns(
                [run('succeeded', '2026-03-04T12:01:00Z'), run('failed', '2026-03-04T11:01:00Z', 'b')],
                NOW,
                0,
            ),
        )
        expect(summary).toContain('2 runs')
        expect(summary).toContain('1 succeeded')
        expect(summary).toContain('1 failed')
    })
})

describe('what this instance depends on', () => {
    test('lists the workers before the connections, because nothing runs without one', () => {
        const rows = healthRows([worker('alpha')], [connection('acme', true)])
        expect(rows.map((row) => row.kind)).toEqual(['worker', 'connection'])
        expect(rows.map((row) => row.label)).toEqual(['alpha', 'acme'])
    })

    test('says what a worker is and how much it can take when it has nothing to report', () => {
        const [row] = healthRows([worker('alpha', { concurrency: 4 })], [])
        expect(row).toMatchObject({ tone: 'good', detail: 'worker · 4 slots', at: null })
    })

    test('counts one slot as one slot', () => {
        const [row] = healthRows([worker('alpha', { concurrency: 1 })], [])
        expect(row.detail).toBe('worker · 1 slot')
    })

    test('says the concern instead, and when the worker was last heard from', () => {
        const [row] = healthRows([worker('alpha', { stale: true, last_seen_at: '2026-01-02T00:00:00Z' })], [])
        expect(row).toMatchObject({ tone: 'critical', at: '2026-01-02T00:00:00Z' })
        expect(row.detail).toBe('has gone quiet')
    })

    test('does not name the worker the row is already headed by', () => {
        const [row] = healthRows([worker('alpha', { stale: true })], [])
        expect(row.label).toBe('alpha')
        expect(row.detail).not.toContain('alpha')
    })

    test('carries what a connection said the last time anything asked', () => {
        const [row] = healthRows([], [connection('acme', true, 'Acme API v3')])
        expect(row).toMatchObject({ tone: 'good', detail: 'Acme API v3', at: '2026-01-01T00:00:00Z' })
    })

    test('carries the refusal whole, and leaves the truncating to the panel', () => {
        const [row] = healthRows([], [connection('acme', false, 'connect timed out after 30s')])
        expect(row).toMatchObject({ tone: 'critical', detail: 'connect timed out after 30s' })
    })

    test('tells a connection nobody has checked from one that answered', () => {
        const [row] = healthRows([], [connection('acme', null)])
        expect(row).toMatchObject({ tone: 'neutral', detail: 'never checked', at: null })
    })
})

describe('the line along the foot of the panel', () => {
    test('says nothing is wrong in one sentence when nothing is, without the metaphor', () => {
        expect(healthNote([worker('alpha')], [connection('acme', true)])).toBe(
            'Every worker and every connection is healthy.',
        )
    })

    // REVERT-PROOF. "3 of 3 connections healthy" spends a clause saying nothing happened.
    test('leaves out a half that is entirely well', () => {
        const note = healthNote(
            [worker('alpha'), worker('beta', { stale: true })],
            [connection('acme', true)],
        )
        expect(note).toBe('1 of 2 workers healthy.')
    })

    test('says both halves when both have something to say', () => {
        const note = healthNote(
            [worker('alpha'), worker('beta', { stale: true })],
            [connection('acme', true), connection('tracker', false)],
        )
        expect(note).toBe('1 of 2 workers healthy · 1 of 2 connections healthy.')
    })

    test('says a fleet that has never registered rather than counting none of none', () => {
        expect(healthNote([], [connection('acme', true)])).toBe('No worker has registered.')
    })

    test('does not promise connections an instance holding none has', () => {
        expect(healthNote([worker('alpha')], [])).toBe(
            'Every worker is healthy, and this instance holds no connections.',
        )
    })
})
