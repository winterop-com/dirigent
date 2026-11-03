import { describe, expect, test } from 'vitest'

import {
    actorOf,
    AUDIT_ACTIONS,
    AUDIT_SUBJECTS,
    auditPath,
    emptyNote,
    EVERY_CHANGE,
    sinceOf,
    subjectOf,
    type AuditEntryOut,
} from '@/lib/audit'
import { LABELS } from '@/lib/labels'

const NOW = Date.parse('2026-11-03T12:00:00Z')

const ENTRY: AuditEntryOut = {
    id: 7,
    created_at: '2026-11-03T11:00:00Z',
    action: 'updated',
    subject_kind: 'schedule',
    subject_id: null,
    subject_code: 'nightly',
    parent_code: 'daily-report',
    fields: ['cron'],
    actor_id: null,
    actor_username: 'agent',
    actor_token: 'mcp-trial',
    actor_token_prefix: 'abcd1234',
    actor_label: 'agent (token mcp-trial)',
}

describe('the audit trail', () => {
    test('asks for nothing but a page when nothing is filtered', () => {
        expect(auditPath(EVERY_CHANGE, null, NOW)).toBe('/audit?limit=50')
    })

    test('sends every filter the server narrows by, and a window as the instant it starts', () => {
        const path = auditPath(
            {
                subject_kind: 'connection',
                action: 'deleted',
                actor: ' ola ',
                subject: 'ops-api',
                window: '24h',
            },
            '41',
            NOW,
        )
        const query = new URLSearchParams(path.split('?')[1])
        expect(Object.fromEntries(query)).toEqual({
            limit: '50',
            subject_kind: 'connection',
            action: 'deleted',
            actor: 'ola',
            subject: 'ops-api',
            since: '2026-11-02T12:00:00.000Z',
            after: '41',
        })
    })

    test('reads a window it does not know as no window', () => {
        expect(sinceOf('', NOW)).toBeNull()
        expect(sinceOf('1y', NOW)).toBeNull()
    })

    test('addresses a subject under what it belongs to', () => {
        expect(subjectOf(ENTRY)).toBe('daily-report/nightly')
        expect(subjectOf({ ...ENTRY, parent_code: null })).toBe('nightly')
    })

    test('names the account and the token it acted through, or the host command where no account did', () => {
        expect(actorOf(ENTRY)).toEqual({ who: 'agent', token: 'mcp-trial' })
        expect(actorOf({ ...ENTRY, actor_username: null, actor_token: null, actor_label: 'dg dev' })).toEqual(
            {
                who: 'dg dev',
                token: null,
            },
        )
    })

    test('says which empty it is', () => {
        expect(emptyNote(EVERY_CHANGE)).toBe(LABELS.audit.empty)
        expect(emptyNote({ ...EVERY_CHANGE, action: 'created' })).toBe(LABELS.audit.empty_filtered)
    })

    test("offers the server's actions and subject kinds", () => {
        expect(AUDIT_ACTIONS).toContain('secrets_supplied')
        expect(AUDIT_SUBJECTS).toEqual([
            'pipeline',
            'trigger_document',
            'schedule',
            'source',
            'alert_rule',
            'connection',
            'schema',
            'user',
            'token',
        ])
    })
})
