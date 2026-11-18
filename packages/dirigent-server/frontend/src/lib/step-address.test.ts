import { describe, expect, test } from 'vitest'

import { matchPath } from 'react-router'

import {
    chosenStep,
    pipelineEditPath,
    pipelineStepPath,
    queryForStep,
    queryWith,
    runStepPath,
} from '@/lib/step-address'

describe('a chosen step as an address', () => {
    test('is the run or the pipeline with the step after it', () => {
        expect(runStepPath('r-1', null)).toBe('/runs/r-1')
        expect(runStepPath('r-1', 'org_units_by_level')).toBe('/runs/r-1/org_units_by_level')
        expect(pipelineStepPath('health', 'jobs')).toBe('/pipelines/health/jobs')
    })

    test('keeps the tab and drops the element and the try of the step before', () => {
        expect(queryForStep('tab=report&item=i-1&attempt=a-1')).toBe('?tab=report')
        expect(queryForStep('item=i-1')).toBe('')
    })

    test('names an element or a try, and stops naming it', () => {
        expect(queryWith('tab=report', 'attempt', 'a-1')).toBe('?tab=report&attempt=a-1')
        expect(queryWith('attempt=a-1', 'attempt', null)).toBe('')
    })

    test('chooses a step the graph holds, and says so of one it does not', () => {
        expect(chosenStep('jobs', ['jobs'])).toEqual({ kind: 'step', code: 'jobs' })
        expect(chosenStep('nope', ['jobs'])).toEqual({ kind: 'unknown', code: 'nope' })
        expect(chosenStep(undefined, ['jobs'])).toEqual({ kind: 'none' })
        // While the graph is still being read nothing is called unknown.
        expect(chosenStep('nope', null)).toEqual({ kind: 'none' })
    })
})

describe("a pipeline's editor and its steps", () => {
    test('a step keyed edit is a step of the page, never the editor', () => {
        const step = pipelineStepPath('health', 'edit')
        expect(step).not.toBe(pipelineEditPath('health'))
        expect(matchPath('/pipelines/:code/$edit', step)).toBeNull()
        expect(matchPath('/pipelines/:code/$edit', pipelineEditPath('health'))?.params.code).toBe('health')
    })
})
