import { describe, expect, test } from 'vitest'

import { elementDays, stepsOf, type ItemHealth, type ItemStats } from '@/lib/item-stats'

function aRow(over: Partial<ItemHealth> = {}): ItemHealth {
    return {
        step: 'reachable',
        item: 'https://chap.example.org',
        runs: 0,
        succeeded: 0,
        failed: 0,
        skipped: 0,
        uptime: null,
        p50_duration_ms: null,
        p95_duration_ms: null,
        last_status: 'succeeded',
        last_run_id: 'r1',
        last_at: null,
        last_failed_at: null,
        last_error: null,
        days: [],
        ...over,
    }
}

describe('an element drawn as days', () => {
    const today = new Date('2026-03-10T12:00:00Z')

    test('every day of the window is drawn, oldest first, ending today', () => {
        const days = elementDays(aRow(), today, 3)
        expect(days.map((day) => day.date)).toEqual(['2026-03-08', '2026-03-09', '2026-03-10'])
    })

    test('a day with failures is the share that succeeded, and a day without runs is not down', () => {
        const row = aRow({
            days: [
                { day: '2026-03-09', succeeded: 3, failed: 1, skipped: 0 },
                { day: '2026-03-10', succeeded: 0, failed: 0, skipped: 2 },
            ],
        })
        expect(elementDays(row, today, 3).map((day) => [day.uptime, day.failed, day.ran])).toEqual([
            [null, 0, 0],
            [0.75, 1, 4],
            [null, 0, 0],
        ])
    })
})

describe('the steps a record names', () => {
    test('are the server order, each once', () => {
        const stats: ItemStats = {
            pipeline: 'checks',
            window: { start: '2026-03-03T12:00:00Z', end: '2026-03-10T12:00:00Z' },
            items: [aRow(), aRow({ item: 'b' }), aRow({ step: 'answers' })],
        }
        expect(stepsOf(stats)).toEqual(['reachable', 'answers'])
    })
})
