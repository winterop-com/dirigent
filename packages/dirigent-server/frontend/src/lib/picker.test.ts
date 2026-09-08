import { describe, expect, it } from 'vitest'

import { matchesOption, type PickerOption } from '@/lib/picker'

const NIGHTLY: PickerOption = { value: 'nightly-etl', label: 'Nightly load', aside: 'nightly-etl' }
const OSLO: PickerOption = { value: 'Europe/Oslo', label: 'Europe/Oslo', aside: 'UTC+2' }

describe('what a picker narrows to', () => {
    it('finds a row by the title it is headed with', () => {
        expect(matchesOption(NIGHTLY, 'nightly load')).toBe(true)
    })

    it('finds the same row by the code it is addressed by', () => {
        expect(matchesOption(NIGHTLY, 'etl')).toBe(true)
    })

    it('narrows on every term rather than widening', () => {
        expect(matchesOption(NIGHTLY, 'load etl')).toBe(true)
        expect(matchesOption(NIGHTLY, 'load hourly')).toBe(false)
    })

    it('offers everything to a query that asked nothing', () => {
        expect(matchesOption(NIGHTLY, '')).toBe(true)
        expect(matchesOption(NIGHTLY, '   ')).toBe(true)
    })

    it('reads the machine half of a row too, which is where a zone offset is', () => {
        expect(matchesOption(OSLO, 'utc+2')).toBe(true)
    })
})
