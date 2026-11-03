import { describe, expect, test } from 'vitest'

import { shortId } from '@/lib/format'
import { LABELS } from '@/lib/labels'

import {
    emptyNote,
    EVERY_RUN,
    filtersFromQuery,
    itemsNote,
    narrowed,
    priorityMark,
    replySent,
    runReportLink,
    runsLink,
    runsPath,
    settledRunsPath,
    tabFromQuery,
    startedAs,
    startedBy,
    waitingForWorkers,
    type RunOut,
    runVerbs,
} from '@/lib/runs'

const RUN: RunOut = {
    id: '11111111-1111-7111-8111-111111111111',
    pipeline: 'nightly-etl',
    pipeline_version: 3,
    priority: 'normal',
    status: 'succeeded',
    params: {},
    triggered_by_kind: 'schedule',
    parent_run_id: null,
    triggered_by_id: null,
    error_params: null,
    triggered_by_label: 'nightly',
    source: null,
    trace_id: null,
    stored_bytes: 0,
    error: null,
    error_code: null,
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
        expect(
            runsPath({ pipeline: 'nightly-etl', status: 'failed', since: '24h', tags: ['climate'] }, null),
        ).toBe('/runs?limit=50&pipeline=nightly-etl&status=failed&since=24h&tag=climate')
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
        expect(runsLink({ ...EVERY_RUN, status: 'failed', since: '24h' })).toBe(
            '/runs?status=failed&since=24h',
        )
    })

    test('carries every tag, so "every nightly run that failed" is one address', () => {
        expect(runsLink({ ...EVERY_RUN, status: 'failed', tags: ['nightly', 'acme'] })).toBe(
            '/runs?status=failed&tag=nightly&tag=acme',
        )
    })

    test('escapes a pipeline code rather than composing an address by hand', () => {
        expect(runsLink({ ...EVERY_RUN, pipeline: 'a name/with slash' })).toBe(
            '/runs?pipeline=a+name%2Fwith+slash',
        )
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
        expect(asked('tag=nightly&tag=acme').tags).toEqual(['nightly', 'acme'])
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

describe("a pipeline's settled runs and a run's report", () => {
    test('ask the listing for one pipeline, settled, newest first', () => {
        expect(settledRunsPath('nightly-etl', 6)).toBe('/runs?pipeline=nightly-etl&settled=true&limit=6')
    })

    test("open a run's screen on its report, and read that back from the address", () => {
        const link = runReportLink(RUN.id)
        expect(link).toBe(`/runs/${RUN.id}?tab=report`)
        expect(tabFromQuery(new URLSearchParams(link.split('?')[1]))).toBe('report')
    })

    test('ignore a tab the screen does not open from its address', () => {
        expect(tabFromQuery(new URLSearchParams('tab=output'))).toBeNull()
        expect(tabFromQuery(new URLSearchParams(''))).toBeNull()
    })
})

describe('what started a run', () => {
    test('is a schedule named with its kind, once', () => {
        expect(startedAs(RUN)).toEqual({
            said: 'schedule nightly',
            actor: false,
            from: null,
            recorded: 'nightly',
        })
        const fired = { ...RUN, triggered_by_label: 'schedule nightly' }
        expect(startedAs(fired).said).toBe('schedule nightly')
    })

    test('names a token or a person by the label alone, which already says it was a token', () => {
        const token = {
            ...RUN,
            triggered_by_kind: 'api_token' as const,
            triggered_by_label: 'agent (token mcp-trial)',
        }
        expect(startedAs(token)).toMatchObject({ said: 'agent (token mcp-trial)', actor: true })
        expect(startedAs({ ...RUN, triggered_by_kind: 'user', triggered_by_label: 'admin' }).said).toBe(
            'admin',
        )
    })

    test('says the kind the way a person reads it where nothing else was recorded', () => {
        const token = { ...RUN, triggered_by_kind: 'api_token' as const, triggered_by_label: null }
        expect(startedAs(token)).toMatchObject({ said: 'api token', actor: false })
    })

    test('names a backfill and a source by their kind and code', () => {
        const filled = {
            ...RUN,
            triggered_by_kind: 'backfill' as const,
            triggered_by_label: 'backfill nightly',
        }
        expect(startedAs(filled).said).toBe('backfill nightly')
        const fired = { ...RUN, triggered_by_kind: 'source' as const, triggered_by_label: 'source arrive' }
        expect(startedAs(fired).said).toBe('source arrive')
    })

    test('names a parent run by its short id, and keeps what the server recorded whole', () => {
        const parent = '0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'
        const child = {
            ...RUN,
            triggered_by_kind: 'pipeline' as const,
            parent_run_id: parent,
            triggered_by_id: parent,
            triggered_by_label: `a step of run ${parent}`,
        }
        const started = startedAs(child)
        expect(started.said).toBe(`a step of run ${shortId(parent)}`)
        expect(started.recorded).toBe(`a step of run ${parent}`)
        expect(started.from).toBe(parent)
    })

    test('names the run a rerun repeated by its short id, and who asked for it', () => {
        const original = '0199a1b2-c3d4-7e5f-8a9b-0c1d2e3f4a5b'
        const rerun = {
            ...RUN,
            triggered_by_kind: 'rerun' as const,
            triggered_by_id: original,
            triggered_by_label: `rerun of ${original} by admin`,
        }
        expect(startedAs(rerun)).toMatchObject({
            said: `rerun of ${shortId(original)} by admin`,
            from: original,
        })
        expect(startedAs({ ...rerun, triggered_by_label: `rerun of ${original}` }).said).toBe(
            `rerun of ${shortId(original)}`,
        )
    })
})

describe('who started a run of a pipeline with a source', () => {
    const byHand = { ...RUN, triggered_by_kind: 'user' as const, triggered_by_label: 'admin', source: 'ask' }
    const entered = (via: 'request' | 'hand' | 'sample') => [
        { kind: 'automatic' as const, step_name: 'answer', via: null },
        { kind: 'received' as const, step_name: 'ask', via },
    ]

    test('says a hand run started from the sample or with an input given', () => {
        expect(startedBy(byHand, entered('sample'))).toBe(`by admin, ${LABELS.runs.entered.sample}`)
        expect(startedBy(byHand, entered('hand'))).toBe(`by admin, ${LABELS.runs.entered.hand}`)
    })

    test('says a called run was a call to its source', () => {
        const called = {
            ...RUN,
            triggered_by_kind: 'source' as const,
            triggered_by_label: 'source ask',
            source: 'ask',
        }
        expect(startedBy(called, entered('request'))).toBe(LABELS.runs.a_call('ask'))
    })

    test('says only how it started where the run has no source, or its attempts are not read yet', () => {
        expect(startedBy(RUN, [])).toBe('schedule nightly')
        expect(startedBy(byHand, [])).toBe('by admin')
    })
})

describe('whether a reply reached a caller', () => {
    test('is what the settled reply rendered', () => {
        expect(replySent({ status: 'succeeded', output: { delivered: true } })).toBe(true)
        expect(replySent({ status: 'succeeded', output: { delivered: false } })).toBe(false)
    })

    test('is not known before it settles, or for a step that renders no verdict', () => {
        expect(replySent(null)).toBeNull()
        expect(replySent({ status: 'pending', output: null })).toBeNull()
        expect(replySent({ status: 'succeeded', output: { value: 1 } })).toBeNull()
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

describe("a run's four verbs", () => {
    test('a finished run allows a rerun and says why the rest are shut', () => {
        const verbs = runVerbs('failed')
        expect(verbs.rerun.open).toBe(true)
        expect([verbs.pause.open, verbs.resume.open, verbs.cancel.open]).toEqual([false, false, false])
        expect(verbs.pause.why).not.toBeNull()
    })

    test('a running run pauses and cancels, and is not rerun yet', () => {
        const verbs = runVerbs('running')
        expect([verbs.pause.open, verbs.resume.open, verbs.cancel.open, verbs.rerun.open]).toEqual([
            true,
            false,
            true,
            false,
        ])
    })

    test('a paused run resumes and cancels', () => {
        const verbs = runVerbs('paused')
        expect([verbs.pause.open, verbs.resume.open, verbs.cancel.open]).toEqual([false, true, true])
    })
})
