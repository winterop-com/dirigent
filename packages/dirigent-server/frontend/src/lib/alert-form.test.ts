import { describe, expect, test } from 'vitest'

import {
    ANY_IMPORTANCE,
    floorChosen,
    given,
    IMPORTANCE_FLOORS,
    LOG_TARGET,
    LOG_TARGET_LABEL,
    targetChosen,
    targetOptions,
    unreadyRule,
} from '@/lib/alert-form'
import type { RuleDraft } from '@/lib/alert-form'
import type { ConnectionOut } from '@/lib/connections'
import { kindGlyph, NEUTRAL_GLYPH } from '@/lib/glyphs'

function aDraft(over: Partial<RuleDraft> = {}): RuleDraft {
    return {
        code: 'page-ops',
        scope: 'global',
        pipeline: '',
        throttle: '0s',
        ...over,
    }
}

function aConnection(over: Partial<ConnectionOut> = {}): ConnectionOut {
    return {
        id: 'c1',
        code: 'ops-slack',
        name: null,
        kind: 'slack',
        description: null,
        config: {},
        secret_fields: [],
        last_check_at: null,
        last_check_healthy: null,
        last_check_detail: null,
        created_at: '2026-09-22T09:00:00Z',
        updated_at: '2026-09-22T09:00:00Z',
        ...over,
    }
}

describe('what the target control sends', () => {
    test('the process log is the absence of a connection rather than a channel named on the wire', () => {
        expect(targetChosen(LOG_TARGET)).toBeNull()
    })

    test('every other row is the connection it stands for', () => {
        expect(targetChosen('ops-slack')).toBe('ops-slack')
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

    test('a throttle is a duration, and the absence of one is written as a duration too', () => {
        expect(unreadyRule(aDraft({ throttle: 'soon' }))).toBe('A throttle is a duration, such as 15m.')
        expect(unreadyRule(aDraft({ throttle: '900' }))).toBe('A throttle is a duration, such as 15m.')
        expect(unreadyRule(aDraft({ throttle: '15m' }))).toBeUndefined()
        expect(unreadyRule(aDraft({ throttle: '1h30m' }))).toBeUndefined()
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

describe('the floor a rule fires at', () => {
    test('offers any first, then every importance least to most', () => {
        expect(IMPORTANCE_FLOORS.map((one) => one.value)).toEqual([
            ANY_IMPORTANCE,
            'routine',
            'normal',
            'critical',
        ])
        expect(IMPORTANCE_FLOORS.map((one) => one.label)).toEqual(['Any', 'Routine', 'Normal', 'Critical'])
    })

    test('sends no floor at all where any was chosen, and the level where one was', () => {
        expect(floorChosen(ANY_IMPORTANCE)).toBeNull()
        expect(floorChosen('critical')).toBe('critical')
    })
})

describe('the channels a rule may deliver through', () => {
    test('the log leads, and needs no credential beside it', () => {
        const [first] = targetOptions(['log', 'slack'], [aConnection()])
        expect(first).toEqual({
            value: LOG_TARGET,
            label: LOG_TARGET_LABEL,
            aside: '',
            mark: kindGlyph('log'),
        })
    })

    test('a row is titled the way every listing titles one, wearing the kind it implies', () => {
        const rows = targetOptions(['log', 'slack'], [aConnection({ name: 'Ops Slack' })])
        expect(rows[1]).toEqual({
            value: 'ops-slack',
            label: 'Ops Slack · slack',
            aside: 'ops-slack',
            mark: kindGlyph('slack'),
        })
    })

    test('a connection nobody named is titled by its code, and still says its kind', () => {
        const rows = targetOptions(
            ['log', 'webhook'],
            [aConnection({ code: 'ops-endpoint', kind: 'webhook' })],
        )
        expect(rows[1]).toEqual({
            value: 'ops-endpoint',
            label: 'ops-endpoint · webhook',
            aside: '',
            mark: kindGlyph('webhook'),
        })
    })

    test('every row wears its own kind, and a kind this bundle cannot name wears the neutral one', () => {
        const rows = targetOptions(
            ['log', 'slack', 'teams'],
            [aConnection(), aConnection({ id: 'c2', code: 'ops-teams', kind: 'teams' })],
        )
        expect(rows.map((row) => row.mark)).toEqual([kindGlyph('log'), kindGlyph('slack'), NEUTRAL_GLYPH])
    })

    test('a connection no installed notifier sends through is not a channel', () => {
        const rows = targetOptions(['log', 'slack'], [aConnection({ code: 'hq', kind: 'dhis2' })])
        expect(rows.map((row) => row.value)).toEqual([LOG_TARGET])
    })

    test('the rows stand together by kind, and by title inside a kind', () => {
        const rows = targetOptions(
            ['log', 'slack', 'webhook'],
            [
                aConnection({ id: 'c1', code: 'zulu-hook', kind: 'webhook' }),
                aConnection({ id: 'c2', code: 'beta-slack', kind: 'slack' }),
                aConnection({ id: 'c3', code: 'alpha-slack', kind: 'slack' }),
            ],
        )
        expect(rows.map((row) => row.value)).toEqual([LOG_TARGET, 'alpha-slack', 'beta-slack', 'zulu-hook'])
    })
})
