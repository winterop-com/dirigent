import { afterEach, describe, expect, test } from 'vitest'

import { formatClock, formatInstant } from '@/lib/format'
import {
    currentOffset,
    DEFAULT_TIMES,
    isTimesMode,
    offsetMinutes,
    TIMES_MODES,
    timesMode,
    zoneOf,
    zoneSuffix,
} from '@/lib/times'

/** An afternoon instant, so no rendering of it crosses a date boundary in any zone. */
const NOON = '2026-06-01T12:34:00Z'

afterEach(() => {
    timesMode.set(DEFAULT_TIMES)
})

describe('which clock instants are read against', () => {
    test('is this machine unless somebody says otherwise', () => {
        expect(DEFAULT_TIMES).toBe('local')
        expect(TIMES_MODES).toContain(DEFAULT_TIMES)
    })

    test('a stored value this build does not have reads as the default rather than refusing', () => {
        expect(isTimesMode('mars')).toBe(false)
        expect(isTimesMode(null)).toBe(false)
        expect(isTimesMode('utc')).toBe(true)
    })

    test('the local setting names no zone, so Intl uses whatever this browser is set to', () => {
        expect(zoneOf('local')).toBeUndefined()
        expect(zoneOf('utc')).toBe('UTC')
    })

    test('a UTC reading is marked, so it cannot be mistaken for a local one', () => {
        expect(zoneSuffix('utc')).toBe(' UTC')
        expect(zoneSuffix('local')).toBe('')
    })

    test('the offset a setting reads against is zero in UTC and this machine otherwise', () => {
        const at = new Date(NOON)
        expect(offsetMinutes('utc', at)).toBe(0)
        expect(offsetMinutes('local', at)).toBe(-at.getTimezoneOffset())
    })

    test('the offset the app is reading against follows the store, as the formatters do', () => {
        timesMode.set('utc')
        expect(currentOffset(new Date(NOON))).toBe(0)
    })
})

describe('the formatters consult the store', () => {
    // REVERT-PROOF against a formatter that stopped asking: 12:34 UTC is 12:34 only in UTC, and
    // this asserts the reading rather than comparing one call against another.
    test('a clock time in UTC is the instant the wire carried', () => {
        timesMode.set('utc')
        expect(formatClock(NOON)).toContain('12:34')
    })

    test('an instant in UTC says which clock it was read against', () => {
        timesMode.set('utc')
        expect(formatInstant(NOON)).toContain(' UTC')
    })

    test("an instant on the local clock is not marked, because it is the reader's own", () => {
        timesMode.set('local')
        expect(formatInstant(NOON)).not.toContain(' UTC')
    })

    test('switching the store moves what is already rendered next time it is rendered', () => {
        timesMode.set('local')
        const local = formatInstant(NOON)
        timesMode.set('utc')
        expect(formatInstant(NOON)).not.toBe(local)
    })

    test('nothing at all is still an em-dash rather than an invented time', () => {
        timesMode.set('utc')
        expect(formatInstant(null)).toBe('--')
        expect(formatClock(undefined)).toBe('--')
    })
})
