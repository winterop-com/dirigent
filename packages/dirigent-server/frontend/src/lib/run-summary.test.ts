import { describe, expect, test } from 'vitest'

import { countsShown, groupedLink, pipelineRunsLink, summaryPath, viewFromQuery } from '@/lib/run-summary'
import { EVERY_RUN } from '@/lib/runs'

describe('the grouped view in the address', () => {
    test('opens grouped only when asked, on 24h unless it names a window it offers', () => {
        expect(viewFromQuery(new URLSearchParams(''))).toEqual({ grouped: false, window: '24h' })
        expect(viewFromQuery(new URLSearchParams('group=pipeline&window=7d'))).toEqual({
            grouped: true,
            window: '7d',
        })
        expect(viewFromQuery(new URLSearchParams('group=pipeline&window=30d')).window).toBe('24h')
    })

    test('carries the filters it reads, and reads back what it wrote', () => {
        const link = groupedLink({ ...EVERY_RUN, status: 'failed', tags: ['nightly'] }, '1h')
        expect(link).toBe('/runs?group=pipeline&window=1h&status=failed&tag=nightly')
        expect(viewFromQuery(new URLSearchParams(link.split('?')[1]))).toEqual({
            grouped: true,
            window: '1h',
        })
    })

    test("opens a pipeline's runs over the window its row was read in", () => {
        expect(pipelineRunsLink('every-ten', '24h')).toBe('/runs?pipeline=every-ten&since=24h')
    })
})

describe('the summary read', () => {
    test("asks for the status of each pipeline's newest run", () => {
        expect(summaryPath({ ...EVERY_RUN, status: 'failed', pipeline: 'p' }, '7d')).toBe(
            '/runs/$summary?since=7d&pipeline=p&latest=failed',
        )
    })

    test('draws the states a pipeline has runs in, in state order, none at zero', () => {
        expect(countsShown({ failed: 3, succeeded: 140, cancelled: 0 })).toEqual([
            { status: 'succeeded', runs: 140 },
            { status: 'failed', runs: 3 },
        ])
    })
})
