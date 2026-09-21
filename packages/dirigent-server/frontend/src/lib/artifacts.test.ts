import { afterEach, describe, expect, test, vi } from 'vitest'

import { ApiError, forgetConfig } from '@/lib/api'
import {
    artifactPath,
    artifactUrl,
    artifactsPath,
    MARKDOWN_CONTENT_TYPE,
    readReportDocument,
    reportArtifact,
    type ArtifactOut,
} from '@/lib/artifacts'

/** One artifact row, with only what a test is asking about spelled out. */
function artifact(over: Partial<ArtifactOut>): ArtifactOut {
    return {
        id: '11111111-1111-7111-8111-111111111111',
        step_name: null,
        content_type: 'application/json',
        size_bytes: 12,
        uri: null,
        created_at: '2026-03-04T11:00:00Z',
        ...over,
    }
}

describe('reportArtifact', () => {
    test('a run with no artifacts has no report', () => {
        expect(reportArtifact([])).toBeNull()
    })

    test('the run-level markdown row is the report', () => {
        const report = artifact({ id: 'a', step_name: null, content_type: MARKDOWN_CONTENT_TYPE })
        const output = artifact({ id: 'b', step_name: 'extract', content_type: 'application/json' })
        expect(reportArtifact([output, report])).toBe(report)
    })

    test("a step's own markdown output is not the run's report", () => {
        const written = artifact({ id: 'b', step_name: 'render', content_type: MARKDOWN_CONTENT_TYPE })
        expect(reportArtifact([written])).toBeNull()
    })

    test('a run-level artifact of another content type is not the report', () => {
        const other = artifact({ step_name: null, content_type: 'application/json' })
        expect(reportArtifact([other])).toBeNull()
    })
})

describe('artifactUrl', () => {
    test('the content path is composed onto the prefix the instance mounted at', () => {
        expect(artifactUrl('/api/v1', 'abc')).toBe('/api/v1/artifacts/abc')
    })

    test('an id is escaped rather than written into the path as it stands', () => {
        expect(artifactPath('a/b')).toBe('/artifacts/a%2Fb')
    })
})

describe('artifactsPath', () => {
    test('a first page asks for a limit and no cursor', () => {
        expect(artifactsPath('run-1', null, 50)).toBe('/runs/run-1/artifacts?limit=50')
    })

    test('a following page carries the cursor it continues from', () => {
        expect(artifactsPath('run-1', 'cursor-2', 50)).toBe('/runs/run-1/artifacts?limit=50&after=cursor-2')
    })
})

/** One canned answer, in the shape `fetch` hands back for a body read either way. */
function answer(status: number, body: unknown): Response {
    return {
        ok: status < 400,
        status,
        json: () => Promise.resolve(body),
        text: () => Promise.resolve(JSON.stringify(body)),
    } as unknown as Response
}

/** The refusal an artifact read answers with when the object its row names is not in storage. */
const OBJECT_MISSING = {
    status: 404,
    title: 'Not Found',
    detail:
        'there is nothing at file:///artifacts/runs/r/report.md: run r (attempt -) has an artifact ' +
        'row and storage has no object; restore the artifact root from the backup that matches ' +
        'this database, or prune the run',
    code: 'artifacts.object_missing',
    params: { uri: 'file:///artifacts/runs/r/report.md', run: 'r', attempt: '-' },
    problems: [],
}

describe('readReportDocument', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
        forgetConfig()
    })

    test('a document whose object is gone reaches the screen as the refusal it is', async () => {
        const report = artifact({ step_name: null, content_type: MARKDOWN_CONTENT_TYPE })
        vi.stubGlobal('fetch', (url: string) => {
            if (url === '/config.json')
                return Promise.resolve(answer(200, { api_prefix: '/api/v1', version: '0' }))
            if (url.includes('/runs/')) return Promise.resolve(answer(200, { items: [report], next: null }))
            return Promise.resolve(answer(404, OBJECT_MISSING))
        })

        const refused = await readReportDocument('r').catch((error: unknown) => error)

        expect(refused).toBeInstanceOf(ApiError)
        expect((refused as ApiError).problem.code).toBe('artifacts.object_missing')
        expect((refused as ApiError).problem.detail).toContain('restore the artifact root')
    })
})
