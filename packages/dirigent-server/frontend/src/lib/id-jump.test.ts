import { describe, expect, it } from 'vitest'

import { ApiError, problemOf } from '@/lib/api'
import { addressOfId, attemptPath, idOf, idResults } from '@/lib/id-jump'
import type { AttemptDetail } from '@/lib/runs'

const RUN = '01a1a11a-0000-7000-8000-000000000001'
const ATTEMPT = '01A1A11A-0000-7000-8000-000000000002'

describe('an id pasted into the palette', () => {
    it('is an id only when it is one whole', () => {
        expect(idOf(`  ${ATTEMPT} `)).toBe(ATTEMPT.toLowerCase())
        expect(idOf('runs')).toBeNull()
        expect(idOf(`${RUN} extra`)).toBeNull()
    })

    it('is the one row the palette finds for it, and a query that is no id finds none', () => {
        const [group] = idResults(` ${RUN}`)
        expect(group.results.map((result) => result.id)).toEqual([RUN])
        expect(idResults('runs')).toEqual([])
    })

    it('opens an attempt as its run with its step chosen and the try marked', async () => {
        const read = (id: string) =>
            Promise.resolve({
                id,
                run_id: RUN,
                step_name: 'load data',
                pipeline: 'demo',
            } as AttemptDetail)
        expect(await addressOfId('a-try', read)).toBe(`/runs/${RUN}/load%20data?attempt=a-try`)
        expect(attemptPath({ id: 'x', run_id: RUN, step_name: 'one' })).toBe(`/runs/${RUN}/one?attempt=x`)
    })

    it('opens an id no attempt holds as a run', async () => {
        const read = () => Promise.reject(new ApiError(problemOf(404, null, '/attempts')))
        expect(await addressOfId(RUN, read)).toBe(`/runs/${RUN}`)
    })

    it('does not mistake any other refusal for a run id', async () => {
        const read = () => Promise.reject(new ApiError(problemOf(500, null, '/attempts')))
        await expect(addressOfId(RUN, read)).rejects.toBeInstanceOf(ApiError)
    })
})
