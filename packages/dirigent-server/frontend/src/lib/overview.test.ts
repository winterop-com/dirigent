import { describe, expect, test } from 'vitest'

import type { Page } from '@/lib/api'
import type { ConnectionOut } from '@/lib/connections'
import {
    bucketByStatus,
    connectionsTile,
    counted,
    dayTile,
    needsALook,
    nowTile,
    schedulesTile,
    summarise,
    withPipelines,
    workersTile,
} from '@/lib/overview'
import type { PipelineOut } from '@/lib/pipelines'
import type { RunOut } from '@/lib/runs'
import type { RunStatus } from '@/lib/status'
import { anyTagged, type WorkerOut } from '@/lib/workers'

/** One page of a listing that has been read to the end. */
function whole<T>(items: T[]): Page<T> {
    return { items, next: null }
}

/** One page of a listing there is more of. */
function truncated<T>(items: T[]): Page<T> {
    return { items, next: 'cursor' }
}

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

function pipeline(code: string, schedules: number, over: Partial<PipelineOut> = {}): PipelineOut {
    return {
        id: code,
        code,
        name: null,
        description: null,
        tags: [],
        active: true,
        current_version: 1,
        active_runs: 0,
        schedules,
        webhooks: 0,
        last_run: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...over,
    }
}

describe('counting what was read', () => {
    test('states the rows a whole listing held', () => {
        expect(counted(whole([1, 2, 3]))).toBe('3')
    })

    test('marks a count taken from a page there is more of, because it is not a total', () => {
        expect(counted(truncated([1, 2, 3]))).toBe('3+')
    })
})

describe('a summary names only what happened', () => {
    test('leaves out a state nothing is in', () => {
        expect(
            summarise([
                [3, 'failed'],
                [0, 'finished with errors'],
            ]),
        ).toBe('3 failed.')
    })

    test('joins the states that did happen, in the order they were given', () => {
        expect(
            summarise([
                [1, 'running'],
                [2, 'waiting to be claimed'],
            ]),
        ).toBe('1 running, 2 waiting to be claimed.')
    })

    test('is nothing at all when nothing happened, so the caller says what that means', () => {
        expect(
            summarise([
                [0, 'failed'],
                [0, 'finished with errors'],
            ]),
        ).toBeNull()
    })
})

describe('bucketing a day of runs', () => {
    test('counts each state the page holds', () => {
        const runs = [
            run('succeeded', '2026-01-01T01:00:00Z'),
            run('succeeded', '2026-01-01T02:00:00Z'),
            run('failed', '2026-01-01T03:00:00Z'),
        ]
        expect(bucketByStatus(runs)).toEqual({ succeeded: 2, failed: 1 })
    })

    test('holds no key for a state nothing is in', () => {
        expect(bucketByStatus([run('running', '2026-01-01T01:00:00Z')]).queued).toBeUndefined()
    })

    test('a day with nothing in it says so rather than reading as a clean day', () => {
        const tile = dayTile(whole([]))
        expect(tile.value).toBe('0')
        expect(tile.tone).toBe('neutral')
        expect(tile.note).toContain('Nothing has run')
    })

    test('a clean day is good and counts what succeeded', () => {
        const tile = dayTile(whole([run('succeeded', '2026-01-01T01:00:00Z')]))
        expect(tile.tone).toBe('good')
        expect(tile.note).toBe('1 succeeded.')
    })

    test('one failure outranks any number of runs that finished with errors', () => {
        const tile = dayTile(
            whole([
                run('completed_with_errors', '2026-01-01T01:00:00Z'),
                run('completed_with_errors', '2026-01-01T02:00:00Z'),
                run('failed', '2026-01-01T03:00:00Z'),
            ]),
        )
        expect(tile.tone).toBe('critical')
        expect(tile.note).toBe('2 finished with errors, 1 failed.')
    })

    // REVERT-PROOF. Count a state at zero and this fails: a day nothing was cancelled in is a
    // day the sentence has no clause to spend on cancellations.
    test('names every settled state that happened and no state that did not', () => {
        const tile = dayTile(
            whole([run('succeeded', '2026-01-01T01:00:00Z'), run('failed', '2026-01-01T02:00:00Z')]),
        )
        expect(tile.note).toBe('1 succeeded, 1 failed.')
        expect(tile.note).not.toContain('cancelled')
        expect(tile.note).not.toContain('0')
    })

    test('a day that has only started says nothing settled rather than reading as clean', () => {
        const tile = dayTile(whole([run('running', '2026-01-01T01:00:00Z')]))
        expect(tile.tone).toBe('neutral')
        expect(tile.note).toBe('Nothing has finished.')
    })

    test('a truncated day is counted as at least what was read', () => {
        expect(dayTile(truncated([run('succeeded', '2026-01-01T01:00:00Z')])).value).toBe('1+')
    })
})

describe('what is happening right now', () => {
    test('is running plus queued, out of the same page', () => {
        const tile = nowTile(
            whole([
                run('running', '2026-01-01T01:00:00Z'),
                run('queued', '2026-01-01T02:00:00Z'),
                run('queued', '2026-01-01T03:00:00Z'),
                run('succeeded', '2026-01-01T04:00:00Z'),
            ]),
        )
        expect(tile.value).toBe('3')
        expect(tile.note).toBe('1 running, 2 waiting to be claimed.')
        expect(tile.tone).toBe('info')
    })

    test('nothing waiting to be claimed is a clause the tile does not spend', () => {
        expect(nowTile(whole([run('running', '2026-01-01T01:00:00Z')])).note).toBe('1 running.')
    })

    test('an idle instance is neutral rather than good, because idle is not an achievement', () => {
        expect(nowTile(whole([run('succeeded', '2026-01-01T01:00:00Z')])).tone).toBe('neutral')
    })
})

describe('the workers tile states the worst fact', () => {
    test('counts the workers that are answering against every worker read', () => {
        const tile = workersTile(whole([worker('a'), worker('b', { status: 'stopped' })]))
        expect(tile.value).toBe('1 of 2')
    })

    test('says so when there is nothing to say', () => {
        expect(workersTile(whole([worker('a')])).note).toBe('Every worker is answering.')
        expect(workersTile(whole([worker('a')])).tone).toBe('good')
    })

    // REVERT-PROOF. Break the ordering in `worstConcern` -- return the first concern found, or
    // reorder CONCERNS -- and this fails: the draining worker sorts first in the listing and a
    // tile that reported it would be hiding the one nobody has heard from.
    test('a silent worker outranks a draining one that sorts before it', () => {
        const tile = workersTile(whole([worker('a', { status: 'draining' }), worker('b', { stale: true })]))
        expect(tile.note).toBe('b has gone quiet.')
        expect(tile.tone).toBe('critical')
    })

    // REVERT-PROOF. A worker running a catalog this server does not have answers perfectly well
    // and will run something other than what it was asked for. Drop `code_matches_server` from
    // `concernOf` and this fails.
    test('a mismatched catalog outranks a stopped worker', () => {
        const tile = workersTile(whole([worker('a', { status: 'stopped' }), worker('b', { code_matches_server: false })]))
        expect(tile.note).toBe('b is running a different catalog from this server.')
        expect(tile.tone).toBe('critical')
    })

    test('a silent worker still outranks a mismatched one', () => {
        const tile = workersTile(whole([worker('a', { code_matches_server: false }), worker('b', { stale: true })]))
        expect(tile.note).toBe('b has gone quiet.')
    })

    test('an empty registry is a warning rather than a clean fleet', () => {
        const tile = workersTile(whole([]))
        expect(tile.value).toBe('0')
        expect(tile.tone).toBe('warning')
    })
})

describe('the connections tile', () => {
    test('names the one that did not answer, with what it said', () => {
        const tile = connectionsTile(whole([connection('ok', true), connection('dhis', false, 'connection refused')]))
        expect(tile.value).toBe('1 of 2')
        expect(tile.note).toBe('dhis did not answer: connection refused')
        expect(tile.tone).toBe('critical')
    })

    test('a connection nothing has checked is not a connection that failed', () => {
        const tile = connectionsTile(whole([connection('ok', true), connection('new', null)]))
        expect(tile.tone).toBe('neutral')
        expect(tile.note).toBe('1 has never been checked.')
    })

    test('every connection answering is good', () => {
        expect(connectionsTile(whole([connection('ok', true)])).tone).toBe('good')
    })
})

describe('the schedules tile', () => {
    test('adds up the schedules the pipelines listing counted', () => {
        const tile = schedulesTile(whole([pipeline('a', 2), pipeline('b', 0), pipeline('c', 1)]))
        expect(tile.value).toBe('3')
        expect(tile.note).toBe('Across 2 of 3 pipelines.')
    })

    test('says nothing fires on its own rather than showing a bare zero', () => {
        expect(schedulesTile(whole([pipeline('a', 0)])).note).toBe('Nothing on this instance fires on its own.')
    })
})

describe('what needs a look', () => {
    test('merges the two listings newest first', () => {
        const merged = needsALook(
            [run('failed', '2026-01-03T00:00:00Z'), run('failed', '2026-01-01T00:00:00Z')],
            [run('completed_with_errors', '2026-01-02T00:00:00Z')],
        )
        expect(merged.map((one) => one.created_at)).toEqual([
            '2026-01-03T00:00:00Z',
            '2026-01-02T00:00:00Z',
            '2026-01-01T00:00:00Z',
        ])
    })

    test('shows no more rows than a feed has room for', () => {
        const many = Array.from({ length: 20 }, (_, index) => run('failed', `2026-01-0${String((index % 9) + 1)}T00:00:00Z`, `run-${String(index)}`))
        expect(needsALook(many, [], 6)).toHaveLength(6)
    })
})

describe('joining a run that wants somebody to what its pipeline is called', () => {
    const failing = run('failed', '2026-01-01T03:00:00Z', 'run-1')

    test('heads it by the name the pipelines listing carries', () => {
        const [entry] = withPipelines([failing], [pipeline('nightly', 0, { name: 'Nightly refresh' })])
        expect(entry.name).toBe('Nightly refresh')
    })

    test('leaves a pipeline the listing did not reach with no name, so the code heads it', () => {
        const [entry] = withPipelines([failing], [])
        expect(entry.name).toBeNull()
        expect(entry.failedStep).toBeNull()
    })

    test('names the step the run itself carries, whatever the pipelines listing says', () => {
        const [entry] = withPipelines([{ ...failing, failed_step: 'load' }], [pipeline('nightly', 0)])
        expect(entry.failedStep).toBe('load')
    })
})

describe('the workers listing draws a Tags column only where a tag exists', () => {
    test('says no when nothing is tagged, which is the instance that never routes', () => {
        expect(anyTagged([])).toBe(false)
        expect(anyTagged([worker('a'), worker('b')])).toBe(false)
    })

    test('says yes as soon as one worker carries one tag', () => {
        expect(anyTagged([worker('a'), worker('b', { tags: ['docker'] })])).toBe(true)
    })
})
