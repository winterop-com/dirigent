import { describe, expect, test } from 'vitest'

import {
    connectionsHealth,
    connectionsNote,
    DOTS,
    editedConfig,
    healthOf,
    mintedConfig,
    patchBody,
    REDACTED,
    settingFields,
    settingsSummary,
    withCheck,
    type ConnectionOut,
} from '@/lib/connections'

/** A secret nobody may ever see on a screen, whatever a config claims to hold. */
const CREDENTIAL = 'hunter2-the-actual-password'

const ROW: ConnectionOut = {
    id: '11111111-1111-7111-8111-111111111111',
    code: 'postman-echo',
    name: null,
    kind: 'http',
    description: 'The public demo service.',
    config: {
        base_url: 'https://postman-echo.com',
        basic_username: 'postman',
        basic_password: REDACTED,
        bearer_token: null,
    },
    secret_fields: ['basic_password', 'bearer_token'],
    last_check_at: null,
    last_check_healthy: null,
    last_check_detail: null,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
}

describe('the settings line under a connection title', () => {
    test('names each setting and draws every stored secret as dots', () => {
        expect(settingsSummary(ROW)).toBe(
            `base_url=https://postman-echo.com · basic_username=postman · basic_password ${DOTS}`,
        )
    })

    /**
     * THE REVERT-PROOF ONE. The API redacts a secret before it answers, so this config cannot
     * arrive -- and that is exactly why the composer must not be the thing relying on it. A
     * summary that passed config values through would put this credential on screen the first
     * time a redaction was missed, and this test is what fails instead.
     */
    test('cannot put a secret on screen even when the config carries one', () => {
        const leaked: ConnectionOut = { ...ROW, config: { ...ROW.config, basic_password: CREDENTIAL } }
        const line = settingsSummary(leaked)
        expect(line).not.toContain(CREDENTIAL)
        expect(line).not.toContain('hunter2')
        expect(line).toContain(`basic_password ${DOTS}`)
    })

    test('leaves a secret nobody stored off the line, because the form is where it is missing', () => {
        expect(settingsSummary({ config: { token: null }, secret_fields: ['token'] })).toBe('no settings')
        expect(settingsSummary({ config: {}, secret_fields: ['token'] })).toBe('no settings')
    })

    test('counts the settings that do not fit rather than running off the end of the row', () => {
        const wide = { config: { a: 1, b: 2, c: 3, d: 4, e: 5, f: 6 }, secret_fields: [] }
        expect(settingsSummary(wide)).toBe('a=1 · b=2 · c=3 · d=4 · +2 more')
    })

    test('never counts away a credential, however many settings come before it', () => {
        const wide = {
            config: { a: 1, b: 2, c: 3, d: 4, e: 5, token: REDACTED },
            secret_fields: ['token'],
        }
        expect(settingsSummary(wide)).toBe(`a=1 · b=2 · c=3 · d=4 · token ${DOTS} · +1 more`)
    })

    test('says a kind with nothing configured has nothing configured', () => {
        expect(settingsSummary({ config: {}, secret_fields: [] })).toBe('no settings')
    })
})

describe('whether a connection answered', () => {
    test('is unchecked until something has checked it', () => {
        expect(healthOf(ROW).state).toBe('unchecked')
        expect(healthOf(ROW).label).toBe('never checked')
    })

    test('reads a healthy check as good, with the instant it was made', () => {
        const view = healthOf({
            last_check_at: '2026-03-01T09:00:00Z',
            last_check_healthy: true,
            last_check_detail: null,
        })
        expect(view.state).toBe('healthy')
        expect(view.tone).toBe('good')
        expect(view.checkedAt).toBe('2026-03-01T09:00:00Z')
    })

    test('carries what a failed check said, which is what the row shows muted', () => {
        const view = healthOf({
            last_check_at: '2026-03-01T09:00:00Z',
            last_check_healthy: false,
            last_check_detail: 'ConnectTimeout: the check raised; the server log has the message',
        })
        expect(view.state).toBe('failed')
        expect(view.tone).toBe('critical')
        expect(view.detail).toContain('ConnectTimeout')
    })
})

describe('the row a check just answered for', () => {
    test('takes the report onto the row rather than reading the listing again', () => {
        const updated = withCheck(ROW, { healthy: true, detail: 'HTTP 200', version: null }, '2026-03-01T09:00:00Z')
        expect(healthOf(updated).state).toBe('healthy')
        expect(updated.last_check_detail).toBe('HTTP 200')
        expect(updated.code).toBe(ROW.code)
    })
})

describe('what an edited connection sends back', () => {
    /**
     * THE OTHER REVERT-PROOF ONE. `PATCH /connections/{code}` takes the config whole, and the
     * marker is how a field says "keep the credential you already have". A form that sent an
     * empty string for an untouched password box would replace the stored credential with an
     * empty one, so what a blank box must contribute is nothing at all.
     */
    test('keeps a stored secret when its box was left blank', () => {
        const body = patchBody(ROW, {}, ROW.name, ROW.description)
        expect(body).toBeNull()

        const changed = patchBody(ROW, { base_url: 'https://example.test' }, ROW.name, ROW.description)
        expect(changed?.config?.basic_password).toBe(REDACTED)
        expect(changed?.config?.basic_password).not.toBe('')
        expect(Object.values(changed?.config ?? {})).not.toContain('')
    })

    test('replaces a secret with what was typed into its box', () => {
        const body = patchBody(ROW, { basic_password: CREDENTIAL }, ROW.name, ROW.description)
        expect(body?.config?.basic_password).toBe(CREDENTIAL)
    })

    test('leaves the description out of the body when nobody touched it', () => {
        const body = patchBody(ROW, { base_url: 'https://example.test' }, ROW.name, ROW.description)
        expect(body).not.toHaveProperty('description')
    })

    test('sends a description that changed, including one that was cleared', () => {
        expect(patchBody(ROW, {}, ROW.name, null)).toEqual({ description: null })
    })

    test('sends a name that changed, and leaves out the one nobody touched', () => {
        expect(patchBody(ROW, {}, 'Postman echo', ROW.description)).toEqual({ name: 'Postman echo' })
        expect(patchBody({ ...ROW, name: 'Postman echo' }, {}, 'Postman echo', ROW.description)).toBeNull()
        expect(patchBody({ ...ROW, name: 'Postman echo' }, {}, null, ROW.description)).toEqual({ name: null })
    })

    test('sends the config whole, because that is what the endpoint replaces', () => {
        expect(editedConfig(ROW, { base_url: 'https://example.test' })).toEqual({
            base_url: 'https://example.test',
            basic_username: 'postman',
            basic_password: REDACTED,
            bearer_token: null,
        })
    })
})

/** A connection kind's published config schema, shaped the way pydantic writes one. */
const SCHEMA = {
    type: 'object',
    properties: {
        base_url: { type: 'string' },
        basic_username: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null },
        basic_password: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null },
        verify_tls: { type: 'boolean', default: true },
    },
    required: ['base_url'],
}

describe('the fields a connection form has a control for', () => {
    test('are the schema\'s, minus every field the kind declares secret', () => {
        const fields = settingFields(SCHEMA, ['basic_password', 'bearer_token'])
        expect(fields.map((field) => field.name)).toEqual(['base_url', 'basic_username', 'verify_tls'])
        expect(fields.find((field) => field.name === 'base_url')?.required).toBe(true)
    })

    test('are none at all before a kind has been chosen, because no schema is known yet', () => {
        expect(settingFields(null, [])).toEqual([])
    })
})

describe('the config a new connection is minted with', () => {
    test('carries the settings and every secret somebody typed', () => {
        expect(mintedConfig({ base_url: 'https://example.test' }, { basic_password: CREDENTIAL })).toEqual({
            base_url: 'https://example.test',
            basic_password: CREDENTIAL,
        })
    })

    /**
     * THE THIRD REVERT-PROOF ONE. An empty string is a password somebody chose, so a connection
     * minted from a form whose boxes were left alone must hold no credential rather than an
     * empty one -- there is nothing here for a blank box to keep.
     */
    test('sets no credential at all for a box nobody typed into', () => {
        const config = mintedConfig({ base_url: 'https://example.test' }, { basic_password: '', bearer_token: '' })
        expect(config).toEqual({ base_url: 'https://example.test' })
        expect(Object.values(config)).not.toContain('')
    })
})

/** One row's three check fields, which is all the note reads of a connection. */
const checked = (healthy: boolean | null) => ({
    last_check_at: healthy === null ? null : '2026-03-01T00:00:00Z',
    last_check_healthy: healthy,
    last_check_detail: null,
})

describe('what the status bar says the connections screen is showing', () => {
    test('states how many of the credentials read answered, which nothing else says', () => {
        expect(connectionsNote([checked(true), checked(false), checked(null)])).toBe(
            '1 of 3 healthy · 1 has never been checked',
        )
    })

    test('does not repeat the count the foot of the table already states', () => {
        expect(connectionsNote([checked(true)])).toBe('1 of 1 healthy')
    })

    test('says of a credential nobody has ever checked that nobody has', () => {
        expect(connectionsNote([checked(null), checked(null)])).toBe(
            '0 of 2 healthy · 2 have never been checked',
        )
    })

    test('takes the noun a sentence about more than connections needs', () => {
        expect(connectionsNote([checked(true), checked(null)], 'connections')).toBe(
            '1 of 2 connections healthy · 1 has never been checked',
        )
    })
})

describe('how a set of connections came out', () => {
    test('counts what answered, what did not, and what nothing has asked', () => {
        expect(connectionsHealth([checked(true), checked(false), checked(null), checked(true)])).toEqual({
            total: 4,
            healthy: 2,
            failed: 1,
            unchecked: 1,
        })
    })

    test('counts nothing at all out of an empty registry', () => {
        expect(connectionsHealth([])).toEqual({ total: 0, healthy: 0, failed: 0, unchecked: 0 })
    })
})

    test('says nothing at all about an empty registry', () => {
        expect(connectionsNote([])).toBeNull()
    })
