import { describe, expect, test } from 'vitest'

import type { JsonMap } from '@/lib/api'
import {
    forEachText,
    forEachValue,
    retryFields,
    retryValues,
    stepFields,
    stepKeyValues,
    withRetryKey,
    withStepKey,
} from '@/lib/step-keys'

/** A document with one fan-out step and one plain one. */
function document(): JsonMap {
    return {
        format: 'dirigent/v1',
        kind: 'pipeline',
        code: 'review-dag',
        steps: {
            per_region: {
                block: 'transform.jq',
                for_each: '${params.regions}',
                items: 'continue',
                config: {},
            },
            cleanup: { block: 'value.const', rule: 'all_done', config: {} },
        },
    }
}

function stepIn(document: JsonMap, step: string): JsonMap {
    return (document.steps as Record<string, JsonMap>)[step]
}

describe('the fields', () => {
    test('are the step members the engine reads, in the definition order', () => {
        expect(stepFields.map((field) => field.name)).toEqual([
            'rule',
            'for_each',
            'items',
            'timeout',
            'poll',
            'deadline',
            'on_timeout',
            'continue_on_failure',
        ])
    })

    test('offer each enum as a select over the values the definition declares', () => {
        const rule = stepFields.find((field) => field.name === 'rule')
        expect(rule?.kind).toBe('select')
        expect(rule?.options.map((option) => option.value)).toEqual([
            'all_success',
            'all_done',
            'one_failed',
            'always',
        ])
        expect(rule?.fallback).toBe('all_success')
        expect(stepFields.find((field) => field.name === 'items')?.options.map((one) => one.value)).toEqual([
            'fail_fast',
            'continue',
        ])
        expect(
            stepFields.find((field) => field.name === 'on_timeout')?.options.map((one) => one.value),
        ).toEqual(['fail', 'skip'])
    })

    test('read a duration as the humane text a document carries', () => {
        for (const name of ['timeout', 'poll', 'deadline']) {
            const field = stepFields.find((one) => one.name === name)
            expect(field?.kind).toBe('text')
            expect(field?.hint).toBe('a duration such as 30s')
        }
    })

    test('are the retry policy members, with its defaults', () => {
        expect(retryFields.map((field) => field.name)).toEqual([
            'max_attempts',
            'backoff',
            'max_backoff',
            'multiplier',
            'jitter',
        ])
        expect(retryFields.find((field) => field.name === 'max_attempts')?.fallback).toBe(1)
        expect(retryFields.find((field) => field.name === 'backoff')?.fallback).toBe('30s')
    })
})

describe('what the controls show', () => {
    test('is only what the step carries', () => {
        expect(stepKeyValues(document(), 'per_region')).toEqual({
            for_each: '${params.regions}',
            items: 'continue',
        })
        expect(stepKeyValues(document(), 'cleanup')).toEqual({ rule: 'all_done' })
    })

    test('reads a literal list as the JSON it is', () => {
        const held = document()
        stepIn(held, 'per_region').for_each = ['east', 'west']
        expect(stepKeyValues(held, 'per_region').for_each).toBe('["east","west"]')
    })

    test('is nothing for a step with no retry policy', () => {
        expect(retryValues(document(), 'cleanup')).toEqual({})
    })
})

describe('for_each', () => {
    test('carries text that reads as a list as a list', () => {
        expect(forEachValue('["east", "west"]')).toEqual(['east', 'west'])
    })

    test('carries a reference, and half-written JSON, as the text it was written as', () => {
        expect(forEachValue('${params.regions}')).toBe('${params.regions}')
        expect(forEachValue('["east"')).toBe('["east"')
    })

    test('round-trips a list through the box', () => {
        expect(forEachValue(forEachText([1, 2]))).toEqual([1, 2])
    })
})

describe('writing a step member', () => {
    test('writes what differs from the default', () => {
        const next = withStepKey(document(), 'cleanup', 'timeout', '5m')
        expect(stepIn(next, 'cleanup').timeout).toBe('5m')
    })

    test('removes the key when what was chosen is the default', () => {
        const next = withStepKey(document(), 'cleanup', 'rule', 'all_success')
        expect(stepIn(next, 'cleanup')).not.toHaveProperty('rule')
    })

    test('removes the key when the box was emptied', () => {
        const next = withStepKey(document(), 'per_region', 'for_each', undefined)
        expect(stepIn(next, 'per_region')).not.toHaveProperty('for_each')
    })

    test('leaves every other step alone', () => {
        const next = withStepKey(document(), 'cleanup', 'rule', 'always')
        expect(stepIn(next, 'per_region')).toEqual(stepIn(document(), 'per_region'))
    })

    test('changes nothing about a step the document does not have', () => {
        const held = document()
        expect(withStepKey(held, 'nowhere', 'rule', 'always')).toBe(held)
    })
})

describe('writing a retry member', () => {
    test('starts a policy carrying only what differs', () => {
        const next = withRetryKey(document(), 'cleanup', 'max_attempts', 3)
        expect(stepIn(next, 'cleanup').retry).toEqual({ max_attempts: 3 })
    })

    test('keeps what the policy already carried', () => {
        const once = withRetryKey(document(), 'cleanup', 'max_attempts', 3)
        const twice = withRetryKey(once, 'cleanup', 'backoff', '1m')
        expect(stepIn(twice, 'cleanup').retry).toEqual({ max_attempts: 3, backoff: '1m' })
    })

    test('removes the whole policy once nothing in it differs', () => {
        const once = withRetryKey(document(), 'cleanup', 'max_attempts', 3)
        const twice = withRetryKey(once, 'cleanup', 'max_attempts', 1)
        expect(stepIn(twice, 'cleanup')).not.toHaveProperty('retry')
    })
})
