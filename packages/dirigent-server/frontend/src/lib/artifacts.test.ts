import { describe, expect, test } from 'vitest'

import {
    artifactPath,
    artifactUrl,
    artifactsPath,
    MARKDOWN_CONTENT_TYPE,
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
