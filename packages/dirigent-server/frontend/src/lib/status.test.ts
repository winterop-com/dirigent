import { describe, expect, test } from 'vitest'

import { attemptSettled, runSettled, statusLabel, statusTokens, stepSettled } from '@/lib/status'

describe('a run that has settled', () => {
    test('is one of the four the client calls terminal', () => {
        for (const status of ['succeeded', 'completed_with_errors', 'failed', 'cancelled']) {
            expect(runSettled(status)).toBe(true)
        }
    })

    test('is not one that is still going', () => {
        expect(runSettled('queued')).toBe(false)
        expect(runSettled('running')).toBe(false)
    })
})

describe('an attempt that has settled', () => {
    test('is one nothing will move again', () => {
        for (const status of ['succeeded', 'failed', 'skipped', 'cancelled']) {
            expect(attemptSettled(status)).toBe(true)
        }
    })

    test('is not one parked on a remote, which is still going', () => {
        expect(attemptSettled('waiting')).toBe(false)
        expect(attemptSettled('pending')).toBe(false)
    })
})

describe('a step that has settled', () => {
    test('is one that will write no more, which is what a log pane says in the past tense', () => {
        for (const outcome of ['succeeded', 'failed', 'skipped', 'cancelled']) {
            expect(stepSettled(outcome)).toBe(true)
        }
    })

    test('is not one that could still write a line', () => {
        expect(stepSettled('pending')).toBe(false)
        expect(stepSettled('running')).toBe(false)
    })
})

describe('the tokens a status indexes', () => {
    test('are the status token and its ink, named for the status itself', () => {
        expect(statusTokens('failed')).toEqual({
            '--chip': 'var(--status-failed)',
            '--chip-ink': 'var(--status-failed-ink)',
        })
    })

    test('spell a run state the way CSS spells a custom property, not the way the wire does', () => {
        expect(statusTokens('completed_with_errors')).toEqual({
            '--chip': 'var(--status-completed-with-errors)',
            '--chip-ink': 'var(--status-completed-with-errors-ink)',
        })
    })

    test('fall back to the neutral pair for a status this bundle was built before', () => {
        // An undefined custom property paints nothing at all, so an unknown state must not
        // index one.
        expect(statusTokens('teleported')).toEqual(statusTokens('pending'))
    })
})

describe('a status as a person reads it', () => {
    test("drops the wire's underscores, which were never a reader's", () => {
        expect(statusLabel('completed_with_errors')).toBe('completed with errors')
    })
})
