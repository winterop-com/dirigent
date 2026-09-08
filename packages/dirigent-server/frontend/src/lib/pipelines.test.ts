import { describe, expect, test } from 'vitest'

import {
    byTitle,
    emptyNote,
    lastRunView,
    pipelinesPath,
    retirement,
    tagsFromQuery,
    tagsPresent,
    triggerSummary,
    type PipelineOut,
} from '@/lib/pipelines'

const ROW: PipelineOut = {
    id: '11111111-1111-7111-8111-111111111111',
    code: 'nightly-etl',
    name: null,
    description: null,
    tags: [],
    active: true,
    current_version: 3,
    active_runs: 0,
    schedules: 0,
    webhooks: 0,
    last_run: null,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
}

describe('the pipelines listing path', () => {
    test('asks for a page and nothing else when no tag was chosen', () => {
        expect(pipelinesPath(null)).toBe('/pipelines?limit=50')
    })

    test('continues from the cursor the previous page gave out', () => {
        expect(pipelinesPath('nightly-etl')).toBe('/pipelines?limit=50&after=nightly-etl')
    })

    test('carries a chosen tag, because the server is what narrows the listing', () => {
        expect(pipelinesPath(null, ['climate'])).toBe('/pipelines?limit=50&tag=climate')
        expect(pipelinesPath('nightly-etl', ['climate'])).toBe('/pipelines?limit=50&after=nightly-etl&tag=climate')
    })

    test('repeats the parameter for a second tag, which is how the server is asked to narrow', () => {
        expect(pipelinesPath(null, ['climate', 'http'])).toBe('/pipelines?limit=50&tag=climate&tag=http')
    })

    test('takes no tags for no filter, so clearing the chips asks the wide question', () => {
        expect(pipelinesPath(null, [])).toBe('/pipelines?limit=50')
    })
})

/** The tags one address asks the listing to open on. */
const asked = (query: string) => tagsFromQuery(new URLSearchParams(query))

describe('the tags an address asks a listing for', () => {
    test('are nothing when the address named none', () => {
        expect(asked('')).toEqual([])
    })

    test('are every tag the address repeated, in the order it named them', () => {
        expect(asked('tag=climate&tag=http')).toEqual(['climate', 'http'])
    })

    test('are lowercased, because that is the only spelling the instance stores', () => {
        expect(asked('tag=Climate')).toEqual(['climate'])
    })

    test('say each tag once, so a doubled parameter narrows once', () => {
        expect(asked('tag=climate&tag=climate')).toEqual(['climate'])
    })

    test('drop an empty tag rather than asking the server about nothing', () => {
        expect(asked('tag=&tag=+&tag=http')).toEqual(['http'])
    })

    test('round-trip the path a filter built back into the filter that built it', () => {
        const tags = ['climate', 'http']
        expect(asked(pipelinesPath(null, tags).split('?')[1])).toEqual(tags)
    })
})

describe('the tags a filter can offer', () => {
    const wearing = (code: string, tags: string[]): PipelineOut => ({ ...ROW, id: code, code, tags })

    test('are the union of what the rows on screen wear, said once each', () => {
        expect(tagsPresent([wearing('a', ['climate', 'http']), wearing('b', ['http', 'dhis2'])])).toEqual([
            'climate',
            'dhis2',
            'http',
        ])
    })

    test('are offered in one order whatever order the rows arrived in', () => {
        expect(tagsPresent([wearing('b', ['http']), wearing('a', ['climate'])])).toEqual(['climate', 'http'])
    })

    test('are nothing at all when nothing is tagged, so the menu has nothing to offer', () => {
        expect(tagsPresent([wearing('a', []), wearing('b', [])])).toEqual([])
        expect(tagsPresent([])).toEqual([])
    })
})

describe('what an empty pipelines table says', () => {
    test('blames the instance when there is nothing and nothing was asked for', () => {
        expect(emptyNote(0, [])).toBe('No pipelines.')
    })

    test('blames the tag when a tag is what emptied it, rather than the instance', () => {
        expect(emptyNote(0, ['climate'])).toBe('No pipeline is tagged climate.')
    })

    test('names both tags when two of them narrowed it to nothing', () => {
        expect(emptyNote(0, ['climate', 'http'])).toBe('No pipeline wears all of climate, http.')
    })

    test('blames the search box when rows were read and none of them match', () => {
        expect(emptyNote(12, ['climate'])).toBe('No loaded pipeline matches that.')
    })
})

describe('what fires a pipeline', () => {
    test('is said as nothing when nothing does', () => {
        expect(triggerSummary({ schedules: 0, webhooks: 0 })).toBe('nothing fires this on its own')
    })

    test('counts each kind, and only the kinds there are', () => {
        expect(triggerSummary({ schedules: 1, webhooks: 0 })).toBe('1 schedule')
        expect(triggerSummary({ schedules: 0, webhooks: 2 })).toBe('2 webhooks')
        expect(triggerSummary({ schedules: 2, webhooks: 1 })).toBe('2 schedules and 1 webhook')
    })
})

describe('the last run of a pipeline', () => {
    const now = Date.parse('2026-03-04T12:00:00Z')

    test('is nothing at all for a pipeline that has never run', () => {
        expect(lastRunView(null, now)).toBeNull()
    })

    test('reads as the state it ended in and how long ago that was', () => {
        const view = lastRunView(
            {
                id: 'r1',
                status: 'succeeded',
                started_at: '2026-03-04T10:00:00Z',
                finished_at: '2026-03-04T11:00:00Z',
                failed_step: null,
            },
            now,
        )
        expect(view).toEqual({
            status: 'succeeded',
            when: '1h ago',
            instant: '2026-03-04T11:00:00Z',
            failedStep: null,
        })
    })

    test('names the step it failed at, which is what says where to look', () => {
        const view = lastRunView(
            {
                id: 'r2',
                status: 'failed',
                started_at: '2026-03-04T11:50:00Z',
                finished_at: '2026-03-04T11:58:00Z',
                failed_step: 'publish',
            },
            now,
        )
        expect(view?.failedStep).toBe('publish')
        expect(view?.status).toBe('failed')
    })

    test('reads from when it started while it is still running', () => {
        const view = lastRunView(
            { id: 'r3', status: 'running', started_at: '2026-03-04T11:58:00Z', finished_at: null, failed_step: null },
            now,
        )
        expect(view?.when).toBe('2m ago')
    })

    test('says it has not started when it has neither instant', () => {
        const view = lastRunView(
            { id: 'r4', status: 'queued', started_at: null, finished_at: null, failed_step: null },
            now,
        )
        expect(view?.when).toBe('not started')
    })
})

describe('a pipeline the instance no longer runs', () => {
    test('is nothing for a live one', () => {
        expect(retirement(ROW)).toBeNull()
    })

    test('is deactivated when its schedules are paused and it cannot be run', () => {
        expect(retirement({ ...ROW, active: false })).toBe('deactivated')
    })
})

describe('the order the pipelines listing reads in', () => {
    const row = (code: string, name: string | null): PipelineOut => ({ ...ROW, code, name })

    // REVERT-PROOF against sorting by the code: these three are headed by their names, and in
    // code order they would read Zebra, Apple, Mango.
    test('is the order of the titles on screen rather than of the codes behind them', () => {
        const sorted = [row('a-one', 'Zebra'), row('b-two', 'Apple'), row('c-three', 'Mango')]
            .toSorted(byTitle)
            .map((found) => found.name)
        expect(sorted).toEqual(['Apple', 'Mango', 'Zebra'])
    })

    test('reads without case, because nobody scans a listing by case', () => {
        const sorted = [row('a', 'beta'), row('b', 'Alpha')].toSorted(byTitle).map((found) => found.name)
        expect(sorted).toEqual(['Alpha', 'beta'])
    })

    test('titles a row with no name by its code, and sorts it there', () => {
        const sorted = [row('m-code', null), row('a-code', 'Zebra')].toSorted(byTitle).map((found) => found.code)
        expect(sorted).toEqual(['m-code', 'a-code'])
    })

    test('breaks a tie on the code, which is the one thing no two rows share', () => {
        const sorted = [row('second', 'Same'), row('first', 'Same')].toSorted(byTitle).map((found) => found.code)
        expect(sorted).toEqual(['first', 'second'])
    })
})
