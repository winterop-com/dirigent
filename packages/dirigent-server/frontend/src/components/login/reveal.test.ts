import { describe, expect, test } from 'vitest'

import { HIDE_PASSWORD_LABEL, SHOW_PASSWORD_LABEL, revealOf } from '@/components/login/reveal'

describe('the password reveal toggle', () => {
    test('hides the value and offers to show it', () => {
        expect(revealOf(false)).toEqual({ inputType: 'password', label: SHOW_PASSWORD_LABEL })
    })

    test('shows the value and offers to hide it', () => {
        expect(revealOf(true)).toEqual({ inputType: 'text', label: HIDE_PASSWORD_LABEL })
    })

    test('flips both the input type and the label together', () => {
        const hidden = revealOf(false)
        const shown = revealOf(true)
        expect(shown.inputType).not.toBe(hidden.inputType)
        expect(shown.label).not.toBe(hidden.label)
    })
})
