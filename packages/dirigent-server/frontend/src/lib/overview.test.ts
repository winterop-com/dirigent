import { describe, expect, test } from 'vitest'

import { needsALook, withPipelines } from '@/lib/overview'
import type { PipelineOut } from '@/lib/pipelines'
import type { RunOut } from '@/lib/runs'
import type { RunStatus } from '@/lib/status'
import { anyTagged, type WorkerOut } from '@/lib/workers'

function run(status: RunStatus, created: string, id = status + created): RunOut {
    return {
        id,
        pipeline: 'nightly',
        pipeline_version: 1,
        priority: 'normal',
        status,
        params: {},
        triggered_by_kind: 'schedule',
        parent_run_id: null,
        triggered_by_label: null,
        trace_id: null,
        error: null,
        error_code: null,
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

function pipeline(code: string, schedules: number, over: Partial<PipelineOut> = {}): PipelineOut {
    return {
        id: code,
        code,
        name: null,
        description: null,
        tags: [],
        importance: 'normal',
        active: true,
        current_version: 1,
        active_runs: 0,
        schedules,
        last_run: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        ...over,
    }
}

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
        const many = Array.from({ length: 20 }, (_, index) =>
            run('failed', `2026-01-0${String((index % 9) + 1)}T00:00:00Z`, `run-${String(index)}`),
        )
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
