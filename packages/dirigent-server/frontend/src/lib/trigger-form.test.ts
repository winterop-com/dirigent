import { describe, expect, it } from 'vitest'

import {
    browserZone,
    given,
    readCron,
    readValues,
    unreadySchedule,
    writeValues,
    zoneOffset,
    zonesOffered,
} from '@/lib/trigger-form'

describe('the pinned parameters, read as a form and as the JSON that form would send', () => {
    it('writes the map out as the object it is', () => {
        expect(writeValues({ day: '2026-01-01', environment: 'production' })).toBe(
            '{\n  "day": "2026-01-01",\n  "environment": "production"\n}',
        )
    })

    it('reads what was written back as the same map', () => {
        const values = { day: '2026-01-01', count: 3, deep: { on: true } }
        expect(readValues(writeValues(values))).toEqual({ ok: true, values })
    })

    it('reads an empty box as pinning nothing, which is what an empty form says', () => {
        expect(readValues('')).toEqual({ ok: true, values: {} })
        expect(readValues('   ')).toEqual({ ok: true, values: {} })
    })

    it('says a list is not the parameters rather than sending one', () => {
        const read = readValues('[1, 2]')
        expect(read.ok).toBe(false)
        expect(read.ok === false && read.message).toBe('The parameters must be a JSON object.')
    })

    it('says what is wrong with a box halfway through being typed, in the parser own words', () => {
        const read = readValues('{"day":')
        expect(read.ok).toBe(false)
        expect(read.ok === false && read.message.length).toBeGreaterThan(0)
    })
})

describe('the zones a schedule is declared in', () => {
    it('offers what this runtime knows, with the browser own among them', () => {
        const zones = zonesOffered()
        expect(zones.length).toBeGreaterThan(100)
        expect(zones).toContain('Europe/Oslo')
        expect(zones).toContain(browserZone())
    })

    it('says what a zone is at, as an offset from UTC', () => {
        expect(zoneOffset('UTC')).toBe('UTC+0')
        expect(zoneOffset('Europe/Oslo', new Date('2026-01-15T12:00:00Z'))).toBe('UTC+1')
        expect(zoneOffset('Europe/Oslo', new Date('2026-07-15T12:00:00Z'))).toBe('UTC+2')
        expect(zoneOffset('America/New_York', new Date('2026-01-15T12:00:00Z'))).toBe('UTC-5')
    })
})

describe('why Create is shut, which is what the button says of itself', () => {
    it('names the pipeline, then the code, then the clock', () => {
        expect(unreadySchedule('', '', '')).toBe('Choose a pipeline.')
        expect(unreadySchedule('nightly-etl', '', '')).toBe('Enter a code.')
        expect(unreadySchedule('nightly-etl', 'nightly', '  ')).toBe('Nothing says when this fires.')
        expect(unreadySchedule('nightly-etl', 'nightly', '0 5 * * *')).toBeUndefined()
    })
})

describe('a box that was emptied', () => {
    it('is that member left unset rather than set to nothing', () => {
        expect(given('  ')).toBeNull()
        expect(given(' Nightly ')).toBe('Nightly')
    })
})

describe('the cron box', () => {
    it("reads an expression back in the catalogue's words, and one it cannot parse as nothing", () => {
        expect(readCron('0 5 * * 1-5')).toBe('At 05:00 on weekdays')
        expect(readCron('0 5 * * *')).toBe('Every day at 05:00')
        expect(readCron('30 2 1,15 * *')).toBe('At 02:30 on the 1st and 15th')
        expect(readCron('0 */6 * * *')).toBe('Every 6 hours')
        expect(readCron('0 5 * * mon,wed,fri')).toBe('At 05:00 on Monday, Wednesday and Friday')
        expect(readCron('0 5 L * *')).toBe('At 05:00 on the last day of the month')
        expect(readCron('0 5 * * 5#2')).toBe('At 05:00 on the 2nd Friday of the month')
        expect(readCron('not cron')).toBeNull()
    })

    it('counts the days of the month the way English does', () => {
        expect(readCron('0 5 1,2,3,11,12,13,21,22,23 * *')).toBe(
            'At 05:00 on the 1st, 2nd, 3rd, 11th, 12th, 13th, 21st, 22nd and 23rd',
        )
    })
})
