import { describe, expect, test } from 'vitest'

import { KIND_FAMILIES, kindFamily, kindLabel } from '@/lib/kinds'

/** Every kind this bundle names itself, plus the shapes a plugin can put on the wire. */
const NAMED = ['operator', 'sensor', 'schedule', 'webhook', 'cron', 'interval', 'one_time']

describe('which family a kind is drawn in', () => {
    test('is total: every string gets one of the declared families', () => {
        const strings = [...NAMED, 'http', 'acme', 'postgres', 's3', '', 'a', 'a kind nobody has written yet']
        for (const kind of strings) {
            expect(KIND_FAMILIES).toContain(kindFamily(kind))
        }
    })

    test('is stable: the same kind is the same colour every time it is asked', () => {
        for (const kind of ['acme', 'http', 'openhim']) {
            expect(kindFamily(kind)).toBe(kindFamily(kind))
        }
    })

    test('keeps the kinds that stand beside one another apart', () => {
        expect(kindFamily('operator')).not.toBe(kindFamily('sensor'))
        expect(kindFamily('schedule')).not.toBe(kindFamily('webhook'))
        expect(kindFamily('cron')).not.toBe(kindFamily('interval'))
    })

    test('does not fall back to one family for everything it has not been told about', () => {
        const unknown = ['http', 'acme', 'postgres', 's3', 'openhim', 'smtp', 'redis', 'kafka', 'sftp', 'gcs']
        expect(new Set(unknown.map(kindFamily)).size).toBeGreaterThan(1)
    })
})

describe('how a kind reads', () => {
    test('the wire spells with underscores and a reader does not', () => {
        expect(kindLabel('one_time')).toBe('one time')
    })

    test('a kind with no underscore is left exactly as the wire wrote it', () => {
        expect(kindLabel('acme')).toBe('acme')
    })
})
