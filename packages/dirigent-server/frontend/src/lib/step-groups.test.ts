import { describe, expect, test } from 'vitest'

import {
    dependsOnSummary,
    fanOutSummary,
    groupProblems,
    retrySummary,
    ruleSummary,
    stepGroups,
    timingSummary,
    type StepGroup,
} from '@/lib/step-groups'
import { STEP_KEYS } from '@/lib/step-keys'

/** The panel's groups for a step carrying nothing, run by an operator. */
function groups(): StepGroup[] {
    return stepGroups({ keys: {}, retry: {}, prerequisites: [], sensor: false })
}

function group(id: string, held: StepGroup[] = groups()): StepGroup {
    const found = held.find((one) => one.id === id)
    if (found === undefined) throw new Error(`no ${id} group`)
    return found
}

/** A summary as one line, which is how a shut row reads it. */
function line(parts: { text: string }[]): string {
    return parts.map((part) => part.text).join(' · ')
}

/** Which parts the document is what says, rather than the definition's defaults. */
function set(parts: { text: string; set: boolean }[]): string[] {
    return parts.filter((part) => part.set).map((part) => part.text)
}

describe('the groups', () => {
    test('are the five the panel reads, in its order', () => {
        expect(groups().map((one) => one.id)).toEqual(['depends_on', 'fan_out', 'timing', 'retry', 'rule'])
    })

    test('file every step member the definition declares', () => {
        const filed = groups().flatMap((one) => one.fields.map((field) => field.name))
        for (const key of STEP_KEYS) {
            // poll is a sensor's key, and this step runs an operator.
            if (key === 'poll') continue
            expect(filed).toContain(key)
        }
    })

    test('carry the controls of their own half and none of another', () => {
        expect(group('fan_out').fields.map((one) => one.name)).toEqual(['for_each', 'items'])
        expect(group('timing').fields.map((one) => one.name)).toEqual(['timeout', 'deadline', 'on_timeout'])
        expect(group('rule').fields.map((one) => one.name)).toEqual(['rule', 'continue_on_failure'])
        expect(group('retry').fields.map((one) => one.name)).toEqual([
            'max_attempts',
            'backoff',
            'max_backoff',
            'multiplier',
            'jitter',
        ])
    })

    test('leave the prerequisites to the picker rather than to a schema', () => {
        expect(group('depends_on').fields).toEqual([])
    })

    test('draw a poll for a sensor, and for an operator that was given one anyway', () => {
        const sensed = stepGroups({ keys: {}, retry: {}, prerequisites: [], sensor: true })
        expect(group('timing', sensed).fields.map((one) => one.name)).toContain('poll')
        const polled = stepGroups({ keys: { poll: '30s' }, retry: {}, prerequisites: [], sensor: false })
        expect(group('timing', polled).fields.map((one) => one.name)).toContain('poll')
    })
})

describe('what a shut Waits for says', () => {
    test('is that a step nothing precedes is a root', () => {
        expect(line(dependsOnSummary([]))).toBe('nothing; this step is a root')
        expect(set(dependsOnSummary([]))).toEqual([])
    })

    test('is the keys it waits for, in the order the document names them', () => {
        expect(dependsOnSummary(['fetch', 'parse'])).toEqual([
            { text: 'fetch', set: true },
            { text: 'parse', set: true },
        ])
    })

    test('is drawn as chips only where there are keys to draw', () => {
        expect(group('depends_on').chips).toBe(false)
        const waiting = stepGroups({ keys: {}, retry: {}, prerequisites: ['fetch'], sensor: false })
        expect(group('depends_on', waiting).chips).toBe(true)
    })
})

describe('what a shut Fan-out says', () => {
    test('is off for a step that maps over nothing', () => {
        expect(line(fanOutSummary({}))).toBe('off')
        expect(set(fanOutSummary({}))).toEqual([])
    })

    test('is what it maps over, and the items policy the engine would use', () => {
        const summary = fanOutSummary({ for_each: '${params.regions}' })
        expect(line(summary)).toBe('${params.regions} · fail_fast')
        expect(set(summary)).toEqual(['${params.regions}'])
    })

    test('says a chosen items policy in the ink of the document', () => {
        const summary = fanOutSummary({ for_each: '${params.regions}', items: 'continue' })
        expect(line(summary)).toBe('${params.regions} · continue')
        expect(set(summary)).toEqual(['${params.regions}', 'continue'])
    })

    test('reads a literal list as the JSON the box holds', () => {
        expect(line(fanOutSummary({ for_each: ['east', 'west'] }))).toBe('["east","west"] · fail_fast')
    })
})

describe('what a shut Timing says', () => {
    test('is what would happen to a step that sets none of it', () => {
        const summary = timingSummary({}, false)
        expect(line(summary)).toBe('no timeout · no deadline · on_timeout fail')
        expect(set(summary)).toEqual([])
    })

    test('is the durations the step carries, each under its own key', () => {
        const summary = timingSummary({ timeout: '30s', deadline: '1h', on_timeout: 'skip' }, false)
        expect(line(summary)).toBe('timeout 30s · deadline 1h · on_timeout skip')
        expect(set(summary)).toEqual(['timeout 30s', 'deadline 1h', 'on_timeout skip'])
    })

    test('say the cadence of a sensor, and nothing at all for an operator', () => {
        expect(line(timingSummary({}, true))).toBe(
            'no timeout · poll its own cadence · no deadline · on_timeout fail',
        )
        expect(line(timingSummary({ poll: '10s' }, true))).toBe(
            'no timeout · poll 10s · no deadline · on_timeout fail',
        )
        expect(line(timingSummary({}, false))).not.toContain('poll')
    })

    test('says a poll an operator was given anyway, because the step carries it', () => {
        expect(line(timingSummary({ poll: '10s' }, false))).toContain('poll 10s')
    })
})

describe('what a shut Retry says', () => {
    test('is off for a step that is tried once', () => {
        expect(line(retrySummary({}))).toBe('off')
        expect(line(retrySummary({ max_attempts: 1 }))).toBe('off')
        expect(set(retrySummary({}))).toEqual([])
    })

    test('is the policy that would run, with the defaults it leaned on in muted ink', () => {
        const summary = retrySummary({ max_attempts: 3 })
        expect(line(summary)).toBe('3 attempts · 30s backoff · ×2 up to 1h')
        expect(set(summary)).toEqual(['3 attempts'])
    })

    test('says what the policy itself chose', () => {
        const summary = retrySummary({ max_attempts: 5, backoff: '1m', multiplier: 3, max_backoff: '10m' })
        expect(line(summary)).toBe('5 attempts · 1m backoff · ×3 up to 10m')
        expect(set(summary)).toEqual(['5 attempts', '1m backoff', '×3 up to 10m'])
    })

    test('mentions jitter only where the policy sets it', () => {
        expect(line(retrySummary({ max_attempts: 3 }))).not.toContain('jitter')
        expect(line(retrySummary({ max_attempts: 3, jitter: 0.5 }))).toBe(
            '3 attempts · 30s backoff · ×2 up to 1h · jitter 0.5',
        )
    })
})

describe('what a shut Rule says', () => {
    test('is the rule the engine would use', () => {
        expect(line(ruleSummary({}))).toBe('all_success')
        expect(set(ruleSummary({}))).toEqual([])
    })

    test('is the rule the step chose', () => {
        expect(set(ruleSummary({ rule: 'all_done' }))).toEqual(['all_done'])
    })

    test('says that dependents run anyway, only where they do', () => {
        expect(line(ruleSummary({ continue_on_failure: true }))).toBe('all_success · continues on failure')
        expect(line(ruleSummary({ continue_on_failure: false }))).toBe('all_success')
    })
})

describe('a group and a refusal', () => {
    test('takes the problems of its own fields and leaves the rest', () => {
        const problems = { timeout: 'timeout is text', rule: 'rule is one of all_success' }
        expect(groupProblems(group('timing'), problems)).toEqual({ timeout: 'timeout is text' })
        expect(groupProblems(group('rule'), problems)).toEqual({ rule: 'rule is one of all_success' })
        expect(groupProblems(group('fan_out'), problems)).toEqual({})
    })
})
