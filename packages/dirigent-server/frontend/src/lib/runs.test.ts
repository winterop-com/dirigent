import { describe, expect, test } from 'vitest'

import {
    emptyNote,
    EVERY_RUN,
    filtersFromQuery,
    itemsNote,
    narrowed,
    priorityMark,
    runsLink,
    runsPath,
    triggerSummary,
    waitingForWorkers,
    type RunOut,
} from '@/lib/runs'

const RUN: RunOut = {
    id: '11111111-1111-7111-8111-111111111111',
    pipeline: 'nightly-etl',
    pipeline_version: 3,
    priority: 'normal',
    status: 'succeeded',
    params: {},
    triggered_by_kind: 'schedule',
    triggered_by_label: 'nightly',
    trace_id: null,
    error: null,
    failed_step: null,
    started_at: '2026-03-04T11:00:00Z',
    finished_at: '2026-03-04T11:02:00Z',
    window_start: null,
    window_end: null,
    created_at: '2026-03-04T11:00:00Z',
}

describe('the runs listing path', () => {
    test('asks for a page and nothing else when nothing is filtered', () => {
        expect(runsPath(EVERY_RUN, null)).toBe('/runs?limit=50')
    })

    test('carries only the four parameters this listing takes', () => {
        expect(runsPath({ pipeline: 'nightly-etl', status: 'failed', since: '24h', tags: ['climate'] }, null)).toBe(
            '/runs?limit=50&pipeline=nightly-etl&status=failed&since=24h&tag=climate',
        )
    })

    test('repeats the tag parameter, so two tags narrow the runs the way they narrow pipelines', () => {
        expect(runsPath({ ...EVERY_RUN, tags: ['climate', 'http'] }, null)).toBe(
            '/runs?limit=50&tag=climate&tag=http',
        )
    })

    test('leaves out a filter nobody set rather than sending it empty', () => {
        expect(runsPath({ ...EVERY_RUN, status: 'running' }, null)).toBe('/runs?limit=50&status=running')
        expect(runsPath({ ...EVERY_RUN, since: '7d' }, null)).toBe('/runs?limit=50&since=7d')
    })

    test('escapes a pipeline code rather than composing a path by hand', () => {
        expect(runsPath({ ...EVERY_RUN, pipeline: 'a name/with slash' }, null)).toBe(
            '/runs?limit=50&pipeline=a+name%2Fwith+slash',
        )
    })

    test('continues from the cursor the previous page gave out', () => {
        expect(runsPath(EVERY_RUN, 'abc')).toBe('/runs?limit=50&after=abc')
    })
})

describe('the address of the listing a number links to', () => {
    test('is the listing itself when nothing was narrowed', () => {
        expect(runsLink(EVERY_RUN)).toBe('/runs')
    })

    test('carries the filters the number was counted under', () => {
        expect(runsLink({ ...EVERY_RUN, status: 'failed', since: '24h' })).toBe('/runs?status=failed&since=24h')
    })

    test('carries every tag, so "every nightly run that failed" is one address', () => {
        expect(runsLink({ ...EVERY_RUN, status: 'failed', tags: ['nightly', 'weather'] })).toBe(
            '/runs?status=failed&tag=nightly&tag=weather',
        )
    })

    test('escapes a pipeline code rather than composing an address by hand', () => {
        expect(runsLink({ ...EVERY_RUN, pipeline: 'a name/with slash' })).toBe('/runs?pipeline=a+name%2Fwith+slash')
    })
})

/** The filters one address opens the listing on. */
const asked = (query: string) => filtersFromQuery(new URLSearchParams(query))

describe('the filters an address asks the listing to open on', () => {
    test('are no filters at all when the address asked for none', () => {
        expect(asked('')).toEqual(EVERY_RUN)
    })

    test('are what a link off the dashboard put in the address', () => {
        expect(asked('status=failed&since=24h')).toEqual({ ...EVERY_RUN, status: 'failed', since: '24h' })
    })

    test('take every tag the address repeated, because repeating one narrows', () => {
        expect(asked('tag=nightly&tag=weather').tags).toEqual(['nightly', 'weather'])
    })

    test('lowercase a shouted tag, because that is the only spelling the instance stores', () => {
        expect(asked('tag=Nightly').tags).toEqual(['nightly'])
    })

    // REVERT-PROOF. A status the state machine does not have is a 422 in place of a listing, and
    // a filter no control can show leaves the bar saying one thing and the rows another.
    test('drop a status this app has no control for', () => {
        expect(asked('status=exploded').status).toBe('')
    })

    test('drop a window this listing does not offer', () => {
        expect(asked('since=3 fortnights').since).toBe('')
        expect(asked('since=7d').since).toBe('7d')
    })

    test('take a pipeline code as it was written, because that is what the server matches', () => {
        expect(asked('pipeline=nightly-etl').pipeline).toBe('nightly-etl')
    })

    test('round-trip a link back into the filters that made it', () => {
        const filters = { pipeline: 'nightly-etl', status: 'running', since: '1h', tags: ['climate', 'http'] }
        expect(asked(runsLink(filters).split('?')[1])).toEqual(filters)
    })
})

describe('what started a run', () => {
    test('is the kind, and who or what it was', () => {
        expect(triggerSummary(RUN)).toEqual({ kind: 'schedule', who: 'nightly' })
    })

    test('spells a kind the way a person reads it rather than the way the wire writes it', () => {
        expect(triggerSummary({ ...RUN, triggered_by_kind: 'api_token' }).kind).toBe('api token')
    })

    test('has nobody to name when the run carries no label', () => {
        expect(triggerSummary({ ...RUN, triggered_by_label: null }).who).toBeNull()
    })

    test('names a backfill, which is a kind of its own and not a firing', () => {
        const filled = { ...RUN, triggered_by_kind: 'backfill' as const, triggered_by_label: 'backfill nightly' }
        expect(triggerSummary(filled)).toEqual({ kind: 'backfill', who: 'backfill nightly' })
    })
})


describe('what an empty runs listing says', () => {
    test('names a way in that is not on this screen when nothing was asked of the listing', () => {
        expect(emptyNote(EVERY_RUN)).toContain('No runs.')
        expect(emptyNote(EVERY_RUN)).toContain('from its own page')
    })

    test('does not claim the instance has never run anything when a filter is what emptied it', () => {
        const filtered = { ...EVERY_RUN, status: 'failed' }
        expect(emptyNote(filtered)).toBe('No run matches these filters.')
    })

    test('counts any of the three filters as having asked something', () => {
        expect(narrowed(EVERY_RUN)).toBe(false)
        expect(narrowed({ ...EVERY_RUN, pipeline: 'nightly' })).toBe(true)
        expect(narrowed({ ...EVERY_RUN, status: 'failed' })).toBe(true)
        expect(narrowed({ ...EVERY_RUN, since: '24h' })).toBe(true)
    })
})

describe('why a queued run has not started', () => {
    test('says nothing when a worker could take it', () => {
        expect(waitingForWorkers(null)).toBeNull()
        expect(waitingForWorkers([])).toBeNull()
    })

    test('names the one tag nobody carries', () => {
        expect(waitingForWorkers(['docker'])).toBe('waiting for a worker carrying docker')
    })

    test('reads as a sentence when more than one tag is missing', () => {
        expect(waitingForWorkers(['docker', 'gpu'])).toBe('waiting for a worker carrying docker and gpu')
        expect(waitingForWorkers(['docker', 'gpu', 'arm64'])).toBe(
            'waiting for a worker carrying docker, gpu and arm64',
        )
    })
})

describe('a run priority, drawn only where it is not the one every run has', () => {
    test('draws nothing for the default, because a column of it would say nothing', () => {
        expect(priorityMark('normal')).toBeNull()
    })

    test('marks the two answers that are not the default', () => {
        expect(priorityMark('high')).toEqual({ label: 'high priority', className: 'text-warning' })
        expect(priorityMark('low')).toEqual({ label: 'low priority', className: 'text-muted-foreground' })
    })
})

describe('what a fan-out says about its elements', () => {
    test('states the count alone where every element came through', () => {
        expect(itemsNote(4, 0)).toBe('4')
    })

    test('states the failures beside the count where there were any', () => {
        expect(itemsNote(4, 1)).toBe('4, 1 failed')
    })

    test('says nothing at all where the step ran no elements', () => {
        expect(itemsNote(0, 0)).toBeNull()
    })
})
