import { afterEach, describe, expect, test } from 'vitest'

import {
    SHORT_ID_LENGTH,
    asJson,
    countedHeading,
    elapsedBetween,
    formatBytes,
    formatDuration,
    formatInstant,
    formatMoment,
    formatRelative,
    formatWindow,
    SHORT_DIGEST_LENGTH,
    shortDigest,
    separatelyUpdated,
    shortId,
    shortenUri,
} from '@/lib/format'
import { DEFAULT_TIMES, timesMode } from '@/lib/times'

afterEach(() => {
    timesMode.set(DEFAULT_TIMES)
})

describe('a measured duration', () => {
    test('is milliseconds while it is under a second, which is what a fast step is', () => {
        expect(formatDuration(0)).toBe('0ms')
        expect(formatDuration(437)).toBe('437ms')
    })

    test('gains a decimal in the first ten seconds and loses it after', () => {
        expect(formatDuration(1500)).toBe('1.5s')
        expect(formatDuration(42_000)).toBe('42s')
    })

    test('is minutes and seconds, then hours and minutes', () => {
        expect(formatDuration(90_000)).toBe('1m 30s')
        expect(formatDuration(3_930_000)).toBe('1h 5m')
    })

    test('says nothing rather than zero when the thing has not finished', () => {
        expect(formatDuration(null)).toBe('--')
        expect(formatDuration(undefined)).toBe('--')
    })
})

describe('the time between two instants', () => {
    test('is the milliseconds between them', () => {
        expect(elapsedBetween('2026-03-01T12:00:00Z', '2026-03-01T12:00:02Z')).toBe(2000)
    })

    test('is nothing while either end is missing, which is a step still running', () => {
        expect(elapsedBetween('2026-03-01T12:00:00Z', null)).toBeNull()
        expect(elapsedBetween(null, '2026-03-01T12:00:02Z')).toBeNull()
    })

    test('is nothing rather than NaN when a timestamp is not one', () => {
        expect(elapsedBetween('yesterday', '2026-03-01T12:00:02Z')).toBeNull()
    })
})

describe('a measured size', () => {
    test('is bytes below a kilobyte', () => {
        expect(formatBytes(0)).toBe('0 B')
        expect(formatBytes(999)).toBe('999 B')
    })

    test('climbs the units, with a decimal only where it says something', () => {
        expect(formatBytes(1536)).toBe('1.5 KB')
        expect(formatBytes(45_000)).toBe('44 KB')
        expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
    })

    test('stops at terabytes rather than inventing a unit', () => {
        expect(formatBytes(1024 ** 5)).toBe('1024 TB')
    })

    test('says nothing for an output that was never written', () => {
        expect(formatBytes(null)).toBe('--')
    })
})

describe('an identifier on screen', () => {
    test('is the tail of the uuid, which is the half that is not the clock', () => {
        expect(shortId('4f0d1a2b-cccc-dddd-eeee-ffffffff0123')).toHaveLength(SHORT_ID_LENGTH)
        expect(shortId('4f0d1a2b-cccc-dddd-eeee-ffffffff0123')).toBe('ffff0123')
    })

    /**
     * A uuid version 7 leads with the millisecond it was minted at, so rows written by one
     * command share their head and nothing about it names any of them.
     */
    test('tells apart two rows minted in the same millisecond, which a head cannot', () => {
        const first = '01a05dd9-1111-7111-8111-aaaaaaaaaaaa'
        const second = '01a05dd9-1111-7111-8111-bbbbbbbbbbbb'
        expect(shortId(first)).not.toBe(shortId(second))
    })
})

describe('a storage uri', () => {
    test('is left alone while it fits', () => {
        expect(shortenUri('scratch://runs/r-1/body.json')).toBe('scratch://runs/r-1/body.json')
    })

    test('keeps the scheme and the end of the key, which is what says which object', () => {
        const long = `s3://a-bucket/${'prefix/'.repeat(12)}the-object.json`
        const short = shortenUri(long)

        expect(short.startsWith('s3://')).toBe(true)
        expect(short.endsWith('the-object.json')).toBe(true)
        expect(short.length).toBeLessThan(long.length)
    })

    test('shortens a uri with no scheme at all rather than refusing it', () => {
        expect(shortenUri('a'.repeat(80)).endsWith('a')).toBe(true)
    })

    test('takes the budget from its caller, for a panel that has been dragged wider', () => {
        expect(shortenUri('scratch://runs/r-1/body.json', 20).length).toBeLessThanOrEqual(21)
    })
})

describe('a timestamp', () => {
    test('says nothing rather than "Invalid Date" when there is none', () => {
        expect(formatInstant(null)).toBe('--')
    })

    test('is handed back unchanged when it is not a timestamp at all', () => {
        expect(formatInstant('not a date')).toBe('not a date')
    })

    // REVERT-PROOF against `toLocaleString`, which spells this `9/2/2026, 11:36:05 AM` in one
    // locale and something else in the next. One spelling, largest field first, everywhere.
    test('is written largest field first rather than in the reader\'s own locale', () => {
        timesMode.set('utc')
        expect(formatInstant('2026-09-02T11:36:05Z')).toBe('2026-09-02 11:36:05 UTC')
    })

    test('holds midnight at hour zero rather than rolling it to twenty-four', () => {
        timesMode.set('utc')
        expect(formatInstant('2026-09-02T00:00:00Z')).toBe('2026-09-02 00:00:00 UTC')
    })

    test('past the recency window a relative reading is a date in that same spelling', () => {
        timesMode.set('utc')
        const when = '2026-01-01T00:00:00Z'
        expect(formatRelative(when, Date.parse('2026-09-02T00:00:00Z'))).toBe('2026-01-01')
    })
})

describe('a firing, read in the zone it fires in', () => {
    test('is the weekday, the day, the month and the clock, largest field first', () => {
        expect(formatMoment('2026-09-08T03:00:00Z', 'Europe/Oslo')).toBe('Tue 8 Sep 05:00')
    })

    test('is read against the schedule own zone rather than the app clock', () => {
        expect(formatMoment('2026-09-08T03:00:00Z', 'UTC')).toBe('Tue 8 Sep 03:00')
    })

    test('is whatever it was given when that is not an instant at all', () => {
        expect(formatMoment('later', 'UTC')).toBe('later')
    })
})

describe('the interval a run covers', () => {
    test('is both instants themselves, with the zone stated once after the pair', () => {
        timesMode.set('utc')
        expect(formatWindow('2026-09-03T00:00:00Z', '2026-09-04T00:00:00Z')).toBe(
            'Thu 3 Sep 00:00 to Fri 4 Sep 00:00 UTC',
        )
    })

    test('carries no zone marker on the clock the machine is already reading', () => {
        timesMode.set('local')
        expect(formatWindow('2026-09-03T00:00:00Z', '2026-09-04T00:00:00Z')).not.toContain('UTC')
    })
})

describe('a value in the read-only pane', () => {
    test('is indented json, which is what a config stanza is read as', () => {
        expect(asJson({ argv: ['echo', 'hi'] })).toBe('{\n  "argv": [\n    "echo",\n    "hi"\n  ]\n}')
    })

    test('is the word null rather than nothing when there is no value', () => {
        expect(asJson(undefined)).toBe('null')
    })
})

describe('how long ago something was', () => {
    const now = Date.parse('2026-03-04T12:00:00Z')

    const ago = (milliseconds: number) => formatRelative(new Date(now - milliseconds).toISOString(), now)
    const ahead = (milliseconds: number) => formatRelative(new Date(now + milliseconds).toISOString(), now)

    test('is "just now" for the last three quarters of a minute, either side of now', () => {
        expect(ago(0)).toBe('just now')
        expect(ago(44_000)).toBe('just now')
        expect(ahead(44_000)).toBe('just now')
    })

    test('rises through minutes, hours and days, one unit at a time', () => {
        expect(ago(120_000)).toBe('2m ago')
        expect(ago(3 * 3_600_000)).toBe('3h ago')
        expect(ago(2 * 86_400_000)).toBe('2d ago')
        expect(ago(30 * 86_400_000)).toBe('30d ago')
    })

    test('gives up on recency past a month and states the date', () => {
        expect(ago(400 * 86_400_000)).not.toMatch(/ago$/)
    })

    test('says nothing rather than "Invalid Date" when there is no instant', () => {
        expect(formatRelative(null, now)).toBe('--')
        expect(formatRelative('not a date', now)).toBe('not a date')
    })

    test('says an instant still to come as the wait for it, in the same units', () => {
        expect(ahead(3 * 60_000)).toBe('in 3m')
        expect(ahead(2 * 3_600_000)).toBe('in 2h')
        expect(ahead(5 * 86_400_000)).toBe('in 5d')
    })

    test('crosses now at the same boundary in both directions', () => {
        expect(ago(45_000)).toBe('1m ago')
        expect(ahead(45_000)).toBe('in 1m')
    })

    test('reads either side of now at the same distance the same way', () => {
        expect(ago(30 * 86_400_000)).toBe('30d ago')
        expect(ahead(30 * 86_400_000)).toBe('in 30d')
    })

    // A schedule declared for next year is no more readable as "in 400d" than a run from last
    // year is as "400d ago": past the window both fall to the date, and the date is the answer.
    test('gives up on a wait past the window and states the date, as the past does', () => {
        timesMode.set('utc')
        expect(ahead(400 * 86_400_000)).toBe('2027-04-08')
    })
})

describe('a version digest on screen', () => {
    const digest = 'sha256:6f1b3c9d2a4e5f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8'

    test('drops the algorithm every digest names and keeps the head that says which', () => {
        expect(shortDigest(digest)).toBe('6f1b3c9d2a4e')
        expect(shortDigest(digest)).toHaveLength(SHORT_DIGEST_LENGTH)
    })

    test('two versions of one pipeline are told apart by it', () => {
        expect(shortDigest(digest)).not.toBe(shortDigest(digest.replace('6f1b', '7a2c')))
    })

    test('a digest written without an algorithm is read from its start', () => {
        expect(shortDigest('abcdef0123456789')).toBe('abcdef012345')
    })
})

describe('a heading over rows', () => {
    test('counts the rows where there are any', () => {
        expect(countedHeading('Artifacts', 3)).toBe('Artifacts (3)')
    })

    test('states the noun alone where there are none, because the empty state says the rest', () => {
        expect(countedHeading('Artifacts', 0)).toBe('Artifacts')
    })
})

describe('whether a row was written again after it was created', () => {
    const NOW = Date.parse('2026-03-01T12:00:00Z')

    test('reads the microseconds a write takes as one instant rather than two', () => {
        expect(separatelyUpdated('2026-03-01T11:59:00.088230Z', '2026-03-01T11:59:00.088232Z', NOW)).toBe(false)
    })

    test('says an edit is its own fact once it reads differently', () => {
        expect(separatelyUpdated('2026-02-01T09:00:00Z', '2026-03-01T11:00:00Z', NOW)).toBe(true)
    })
})
