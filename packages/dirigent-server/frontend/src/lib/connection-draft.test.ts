import { describe, expect, test } from 'vitest'

import {
    connectionBody,
    createShut,
    draftFor,
    NO_DRAFT,
    withKind,
    withSecret,
    withSetting,
} from '@/lib/connection-draft'
import { LABELS } from '@/lib/labels'

const NOTHING_UNREADABLE: ReadonlySet<string> = new Set()

const NO_PROBLEMS: Record<string, string> = {}

/** A draft filled in as far as a form standing in a carried row ever fills one. */
const CARRIED = withSecret(
    withSetting(draftFor('ops-receiver', 'http'), 'base_url', 'http://127.0.0.1'),
    'hmac_secret',
    'typed-here',
)

describe('what a draft sends', () => {
    test('the code and the kind are the ones the caller settled, boxes or no boxes', () => {
        const body = connectionBody(CARRIED)
        expect(body.code).toBe('ops-receiver')
        expect(body.kind).toBe('http')
    })

    test('a secret that was typed goes into the config beside the settings', () => {
        expect(connectionBody(CARRIED).config).toEqual({
            base_url: 'http://127.0.0.1',
            hmac_secret: 'typed-here',
        })
    })

    /**
     * An empty string is a password somebody chose, and a connection minted with one holds a
     * credential nobody meant to give it.
     */
    test('a password box left blank sets nothing at all', () => {
        const untouched = withSecret(CARRIED, 'hmac_secret', '')
        expect(connectionBody(untouched).config).toEqual({ base_url: 'http://127.0.0.1' })
        expect('hmac_secret' in connectionBody(untouched).config).toBe(false)
    })

    test('a title nobody gave is cleared rather than sent as empty text', () => {
        const body = connectionBody({ ...CARRIED, name: '   ', description: '' })
        expect(body.name).toBeNull()
        expect(body.description).toBeNull()
    })

    test('a code is sent trimmed, because it is what every reference to it names', () => {
        expect(connectionBody({ ...CARRIED, code: '  ops-receiver  ' }).code).toBe('ops-receiver')
    })
})

describe('choosing another kind', () => {
    /** A setting belongs to the schema that asked for it, and no other kind takes that key. */
    test('takes the settings and the secrets typed for the last one with it', () => {
        const moved = withKind(CARRIED, 'sql')
        expect(moved.kind).toBe('sql')
        expect(moved.values).toEqual({})
        expect(moved.secrets).toEqual({})
    })

    test('and keeps the code, which is what the thing is addressed by either way', () => {
        expect(withKind(CARRIED, 'sql').code).toBe('ops-receiver')
    })
})

describe('a setting the control answered nothing for', () => {
    test('is cleared from the draft rather than held as undefined', () => {
        const cleared = withSetting(CARRIED, 'base_url', undefined)
        expect('base_url' in cleared.values).toBe(false)
    })
})

describe('why create is shut', () => {
    test('nothing is asked of an empty draft but the two things it is addressed by', () => {
        expect(createShut(NO_DRAFT, NO_PROBLEMS, NOTHING_UNREADABLE)).toBe(LABELS.connections.needs_code)
        expect(createShut(draftFor('ops-receiver', null), NO_PROBLEMS, NOTHING_UNREADABLE)).toBe(
            LABELS.connections.needs_kind,
        )
    })

    test('a setting that is not a value comes before one the schema refuses', () => {
        expect(createShut(CARRIED, { base_url: 'not a url' }, new Set(['timeout']))).toBe(
            LABELS.connections.unreadable_setting,
        )
        expect(createShut(CARRIED, { base_url: 'not a url' }, NOTHING_UNREADABLE)).toBe(
            LABELS.connections.settings_refused,
        )
    })

    test('and nothing shuts a draft the kind would accept', () => {
        expect(createShut(CARRIED, NO_PROBLEMS, NOTHING_UNREADABLE)).toBeUndefined()
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

    /**
     * NOTHING IS READ OUT OF THE DOCUMENT. A carried connection's config can hold a credential
     * in a field the kind declares secret and in one it does not, so the form starts empty and
     * every value in it is typed by a person.
     */
    test('and carries no settings and no secrets out of the document', () => {
        expect(draftFor('ops-receiver', 'http').values).toEqual({})
        expect(draftFor('ops-receiver', 'http').secrets).toEqual({})
    })
})
