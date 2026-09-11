import { describe, expect, test } from 'vitest'

import { given, needsConnection, unreadyRule, unreadyTest } from '@/lib/alert-form'
import type { RuleDraft } from '@/lib/alert-form'

function aDraft(over: Partial<RuleDraft> = {}): RuleDraft {
    return {
        code: 'page-ops',
        scope: 'global',
        pipeline: '',
        notifier: 'log',
        connection: '',
        throttle: '0s',
        ...over,
    }
}

describe('which channels deliver through a credential', () => {
    test('log needs none, because it writes to the process log', () => {
        expect(needsConnection('log')).toBe(false)
    })

    test('every other channel does', () => {
        expect(needsConnection('slack')).toBe(true)
        expect(needsConnection('email')).toBe(true)
        expect(needsConnection('webhook')).toBe(true)
    })

    test('nothing chosen is not a channel that needs one', () => {
        expect(needsConnection('')).toBe(false)
    })
})

describe('why a new rule cannot be declared yet', () => {
    test('a rule that says everything is ready', () => {
        expect(unreadyRule(aDraft())).toBeUndefined()
    })

    test('a rule is addressed by a code', () => {
        expect(unreadyRule(aDraft({ code: '  ' }))).toBe(
            'A rule is addressed by its code, and this one has none.',
        )
    })

    test('a code is the shape every code in this instance is', () => {
        expect(unreadyRule(aDraft({ code: 'Page Ops' }))).toBe('A code is lowercase words joined by - or _.')
        expect(unreadyRule(aDraft({ code: 'page_ops-2' }))).toBeUndefined()
    })

    test('a rule watching one pipeline has to name it', () => {
        expect(unreadyRule(aDraft({ scope: 'pipeline' }))).toBe(
            'A rule watching one pipeline names that pipeline, and this one names none.',
        )
        expect(unreadyRule(aDraft({ scope: 'pipeline', pipeline: 'nightly' }))).toBeUndefined()
    })

    test('a rule delivers through a channel', () => {
        expect(unreadyRule(aDraft({ notifier: '' }))).toBe(
            'A rule delivers through a channel, and this one names none.',
        )
    })

    test('a channel that needs a credential says which one is missing', () => {
        expect(unreadyRule(aDraft({ notifier: 'slack' }))).toBe(
            'The slack channel delivers through a connection, and this one names none.',
        )
        expect(unreadyRule(aDraft({ notifier: 'slack', connection: 'ops-slack' }))).toBeUndefined()
    })

    test('a throttle is a duration, and the absence of one is written as a duration too', () => {
        expect(unreadyRule(aDraft({ throttle: 'soon' }))).toBe('A throttle is a duration, such as 15m.')
        expect(unreadyRule(aDraft({ throttle: '900' }))).toBe('A throttle is a duration, such as 15m.')
        expect(unreadyRule(aDraft({ throttle: '15m' }))).toBeUndefined()
        expect(unreadyRule(aDraft({ throttle: '1h30m' }))).toBeUndefined()
    })
})

describe('why a test cannot be sent yet', () => {
    test('a test goes through a channel', () => {
        expect(unreadyTest('', '')).toBe('A test goes through a channel, and this one names none.')
    })

    test('log needs nothing beside it', () => {
        expect(unreadyTest('log', '')).toBeUndefined()
    })

    test('every other channel needs the credential it delivers through', () => {
        expect(unreadyTest('email', '')).toBe(
            'The email channel delivers through a connection, and this one names none.',
        )
        expect(unreadyTest('email', 'ops-mail')).toBeUndefined()
    })
})

describe('what a box left empty sends', () => {
    test('a box nobody typed in is null on the wire rather than an empty string', () => {
        expect(given('')).toBeNull()
        expect(given('   \n  ')).toBeNull()
    })

    test('a template is sent as it was written, less the whitespace around it', () => {
        expect(given('  {{ run.status }}  ')).toBe('{{ run.status }}')
    })

    test('a body keeps the lines it was written on', () => {
        expect(given('{{ run.pipeline }}\n\n{{ report }}\n')).toBe('{{ run.pipeline }}\n\n{{ report }}')
    })
})
