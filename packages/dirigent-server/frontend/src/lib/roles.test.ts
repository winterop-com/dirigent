import { describe, expect, test } from 'vitest'

import { firstShut, passes, whyShut } from '@/lib/roles'

describe('what a role may do', () => {
    test('an admin passes both gates', () => {
        expect(passes('admin', 'operator')).toBe(true)
        expect(passes('admin', 'admin')).toBe(true)
    })

    test('an operator passes its own gate and not the admin one', () => {
        expect(passes('operator', 'operator')).toBe(true)
        expect(passes('operator', 'admin')).toBe(false)
    })

    test('a viewer passes neither', () => {
        expect(passes('viewer', 'operator')).toBe(false)
        expect(passes('viewer', 'admin')).toBe(false)
    })

    test('an identity nobody has read yet shuts nothing', () => {
        expect(passes(null, 'operator')).toBe(true)
        expect(whyShut(null, 'admin')).toBeUndefined()
    })
})

describe('why a control is shut', () => {
    test('nothing is said where the role passes', () => {
        expect(whyShut('operator', 'operator')).toBeUndefined()
        expect(whyShut('admin', 'admin')).toBeUndefined()
    })

    test('the sentence says the account cannot, and never what another role could', () => {
        expect(whyShut('viewer', 'operator')).toBe('Not available to a viewer.')
        expect(whyShut('viewer', 'admin')).toBe('Not available to a viewer.')
        expect(whyShut('operator', 'admin')).toBe('Not available to an operator.')
    })
})

describe('one sentence out of several reasons', () => {
    test('the first stated reason is the one a control wears', () => {
        expect(firstShut(undefined, 'This one.', 'And this one.')).toBe('This one.')
    })

    test('no reason at all is a control that is not shut', () => {
        expect(firstShut(undefined, undefined)).toBeUndefined()
    })
})
