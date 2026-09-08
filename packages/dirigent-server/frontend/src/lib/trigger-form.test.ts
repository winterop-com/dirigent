import { describe, expect, it } from 'vitest'

import {
    browserZone,
    generatedSecret,
    given,
    mappedPaths,
    readValues,
    unreadySchedule,
    unreadyWebhook,
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
        expect(read.ok === false && read.message).toBe('The parameters are a JSON object.')
    })

    it('says what is wrong with a box halfway through being typed, in the parser own words', () => {
        const read = readValues('{"day":')
        expect(read.ok).toBe(false)
        expect(read.ok === false && read.message.length).toBeGreaterThan(0)
    })
})

describe('a webhook payload mapping, one row per parameter', () => {
    it('sends a path for every row somebody wrote one in', () => {
        expect(mappedPaths({ day: '$.published.date', environment: '$.target.environment' })).toEqual({
            day: '$.published.date',
            environment: '$.target.environment',
        })
    })

    it('leaves out a parameter the payload does not carry', () => {
        expect(mappedPaths({ day: '$.published.date', environment: '', extra: '   ' })).toEqual({
            day: '$.published.date',
        })
    })

    it('sends the path rather than the whitespace around it', () => {
        expect(mappedPaths({ day: '  $.published.date  ' })).toEqual({ day: '$.published.date' })
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

describe('a generated signing secret', () => {
    it('is 32 bytes written as hex, and a different one every time', () => {
        const secret = generatedSecret()
        expect(secret).toMatch(/^[0-9a-f]{64}$/)
        expect(secret).not.toBe(generatedSecret())
    })
})

describe('why Create is shut, which is what the button says of itself', () => {
    it('names the pipeline, then the code, then the clock', () => {
        expect(unreadySchedule('', '', '')).toContain('names none')
        expect(unreadySchedule('nightly-etl', '', '')).toContain('addressed by its code')
        expect(unreadySchedule('nightly-etl', 'nightly', '  ')).toBe('Nothing says when this fires.')
        expect(unreadySchedule('nightly-etl', 'nightly', '0 5 * * *')).toBeUndefined()
    })

    it('asks a webhook for its pipeline and its code and nothing else', () => {
        expect(unreadyWebhook('', 'hook')).toContain('names none')
        expect(unreadyWebhook('webhook-trigger', '  ')).toContain('addressed by its code')
        expect(unreadyWebhook('webhook-trigger', 'hook')).toBeUndefined()
    })
})

describe('a box that was emptied', () => {
    it('is that member left unset rather than set to nothing', () => {
        expect(given('  ')).toBeNull()
        expect(given(' Nightly ')).toBe('Nightly')
    })
})
