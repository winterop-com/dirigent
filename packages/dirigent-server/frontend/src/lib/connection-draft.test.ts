import { describe, expect, test } from 'vitest'

import { connectionBody, createShut, draftFor, NO_DRAFT } from '@/lib/connection-draft'
import { LABELS } from '@/lib/labels'

/** A draft filled in as far as a form standing in a carried row ever fills one. */
const CARRIED = draftFor('ops-receiver', 'http')

/** The settings the kind's form holds, a secret that was typed among them. */
const CONFIG = { base_url: 'http://127.0.0.1', hmac_secret: 'typed-here' }

describe('what a draft sends', () => {
    test('the code and the kind are the ones the caller settled, boxes or no boxes', () => {
        const body = connectionBody(CARRIED, CONFIG)
        expect(body.code).toBe('ops-receiver')
        expect(body.kind).toBe('http')
    })

    test('the config is the one the form holds', () => {
        expect(connectionBody(CARRIED, CONFIG).config).toEqual(CONFIG)
    })

    test('a title nobody gave is cleared rather than sent as empty text', () => {
        const body = connectionBody({ ...CARRIED, name: '   ', description: '' }, CONFIG)
        expect(body.name).toBeNull()
        expect(body.description).toBeNull()
    })

    test('a code is sent trimmed, because it is what every reference to it names', () => {
        expect(connectionBody({ ...CARRIED, code: '  ops-receiver  ' }, CONFIG).code).toBe('ops-receiver')
    })
})

describe('why create is shut', () => {
    test('nothing is asked of an empty draft but the two things it is addressed by', () => {
        expect(createShut(NO_DRAFT)).toBe(LABELS.connections.needs_code)
        expect(createShut(draftFor('ops-receiver', null))).toBe(LABELS.connections.needs_kind)
    })

    test('and nothing shuts a draft that has both', () => {
        expect(createShut(CARRIED)).toBeUndefined()
    })
})

describe('a draft on an identity a document settled', () => {
    test('opens on that code and that kind, with nothing typed into it', () => {
        expect(draftFor('ops-receiver', 'http')).toEqual({
            ...NO_DRAFT,
            code: 'ops-receiver',
            kind: 'http',
        })
    })

    /** A carried connection may declare no kind, and then the form is where one is chosen. */
    test('leaves the kind unchosen where the document declared none', () => {
        expect(draftFor('ops-receiver', null).kind).toBe('')
    })
})
