import { describe, expect, test } from 'vitest'

import { LABELS } from '@/lib/labels'
import {
    attemptSettled,
    dotOf,
    isNews,
    runSettled,
    saysWord,
    STATUSES,
    statusLabel,
    statusTokens,
    stepSettled,
} from '@/lib/status'

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

describe('the states handed to the status parts', () => {
    test('pulse only while something is happening', () => {
        const live = Object.keys(STATUSES).filter((status) => STATUSES[status].live === true)
        expect(live.toSorted()).toEqual(['queued', 'running', 'sending', 'waiting'])
    })

    test('say the words a person reads and draw the color the tokens draw', () => {
        expect(STATUSES.completed_with_errors).toMatchObject({ label: 'completed with errors' })
        expect(STATUSES.paused.color).toBe('pending')
        expect(statusTokens('paused')).toEqual(statusTokens('pending'))
        expect(STATUSES.sending.color).toBe('running')
        expect(STATUSES.sent.color).toBe('succeeded')
    })
})

describe('a dot', () => {
    test('says its word only when the state is news', () => {
        expect(saysWord(isNews({ tone: 'good' }))).toBe(false)
        expect(saysWord(isNews({ tone: 'critical' }))).toBe(true)
        expect(saysWord(isNews({ tone: 'unknown' }))).toBe(true)
        expect(saysWord(isNews({ status: 'succeeded' }))).toBe(false)
        expect(saysWord(isNews({ status: 'paused' }))).toBe(false)
        expect(saysWord(isNews({ status: 'failed' }))).toBe(true)
    })

    test('says it always or never where it is asked to', () => {
        expect(saysWord(false, 'always')).toBe(true)
        expect(saysWord(true, 'never')).toBe(false)
    })

    test('is 8px, hollow only when unknown, and says its word as a tooltip where it does not draw it', () => {
        expect(dotOf({ tone: 'good', label: 'healthy' })).toEqual({
            color: 'var(--good)',
            outline: false,
            size: 'md',
            label: 'healthy',
            say: false,
            tip: 'healthy',
            className: undefined,
        })
        expect(dotOf({ tone: 'unknown', label: 'never checked' })).toMatchObject({
            outline: true,
            say: true,
            tip: undefined,
        })
        expect(dotOf({ status: 'failed' })).toMatchObject({
            color: 'var(--status-failed)',
            label: LABELS.state.run.failed.chip,
            say: true,
        })
    })
})
