import { describe, expect, test } from 'vitest'

import { appliedLine, changesIn, issuesNote, planView, triggerChanges } from '@/lib/pipeline-plan'
import type { ApplyResult, DiffSummary, Materialized, PipelinePlan } from '@/lib/pipelines'

function diff(over: Partial<DiffSummary> = {}): DiffSummary {
    return {
        steps_added: [],
        steps_removed: [],
        steps_changed: [],
        params_changed: false,
        triggers_changed: false,
        settings_changed: false,
        ...over,
    }
}

function plan(over: Partial<PipelinePlan> = {}): PipelinePlan {
    return {
        code: 'convert-one',
        action: 'update',
        digest: 'sha256:abc',
        current_version: 3,
        next_version: 4,
        issues: [],
        diff: diff(),
        ...over,
    }
}

function materialized(over: Partial<Materialized> = {}): Materialized {
    return {
        schedules_created: [],
        schedules_updated: [],
        schedules_removed: [],
        webhooks_created: [],
        webhooks_updated: [],
        webhooks_removed: [],
        ...over,
    }
}

describe('what a plan says', () => {
    test('an update names the version applying would write', () => {
        const view = planView(plan())
        expect(view.headline).toBe('Apply writes version 4 of convert-one')
        expect(view.tone).toBe('good')
        expect(view.applicable).toBe(true)
    })

    test('a create says the pipeline is not here yet', () => {
        const view = planView(plan({ action: 'create', current_version: null, next_version: 1 }))
        expect(view.headline).toBe('Apply creates convert-one at version 1')
        expect(view.applicable).toBe(true)
    })

    test('an unchanged document offers no apply, because applying it writes nothing', () => {
        const view = planView(plan({ action: 'unchanged' }))
        expect(view.headline).toContain('Apply writes nothing')
        expect(view.tone).toBe('quiet')
        expect(view.applicable).toBe(false)
    })

    test('an invalid document is a refusal, and the issues are what it shows instead', () => {
        const issues = [{ location: 'steps.push.config.method', message: 'unknown key' }]
        const view = planView(plan({ action: 'invalid', next_version: null, diff: null, issues }))
        expect(view.headline).toBe('Apply will refuse convert-one')
        expect(view.tone).toBe('critical')
        expect(view.applicable).toBe(false)
        expect(view.issues).toEqual(issues)
        expect(view.changes).toEqual([])
    })
})

describe('what a diff amounts to', () => {
    test('is a line per kind of change, naming the steps in each', () => {
        expect(
            changesIn(
                diff({ steps_added: ['as_csv'], steps_changed: ['parse', 'report'], params_changed: true }),
            ),
        ).toEqual(['steps added: as_csv', 'steps changed: parse, report', 'the parameter schema changed'])
    })

    test('is nothing when the two definitions are the same in every respect', () => {
        expect(changesIn(diff())).toEqual([])
    })

    test('is nothing when the plan carried no diff at all', () => {
        expect(changesIn(null)).toEqual([])
    })

    test('names the settings change in the terms the server summarises it in', () => {
        expect(changesIn(diff({ settings_changed: true, triggers_changed: true }))).toEqual([
            'the triggers changed',
            'the name, description, or concurrency policy changed',
        ])
    })
})

describe('what an apply did', () => {
    test('names the version it wrote', () => {
        const result: ApplyResult = {
            plan: plan(),
            pipeline_id: 'an-id',
            version: 4,
            dry_run: false,
            triggers: materialized(),
        }
        expect(appliedLine(result)).toBe('convert-one is at version 4')
    })

    test('says nothing was written when nothing was', () => {
        const result: ApplyResult = {
            plan: plan({ action: 'unchanged', next_version: null }),
            pipeline_id: 'an-id',
            version: null,
            dry_run: false,
            triggers: materialized(),
        }
        expect(appliedLine(result)).toBe('convert-one was left as it was')
    })

    test('lists what it did to the triggers, and nothing when it left them alone', () => {
        expect(
            triggerChanges(materialized({ schedules_created: ['nightly'], webhooks_removed: ['intake'] })),
        ).toEqual(['schedules created: nightly', 'webhooks removed: intake'])
        expect(triggerChanges(materialized())).toEqual([])
    })
})

describe('what the status bar says about a validation', () => {
    test('counts the issues and says what they mean for an apply', () => {
        expect(issuesNote([{ location: 'steps.push', message: 'no such block' }])).toBe(
            '1 issue — apply will refuse',
        )
        expect(
            issuesNote([
                { location: 'steps.push', message: 'no such block' },
                { location: 'steps.pull', message: 'no such block' },
            ]),
        ).toBe('2 issues — apply will refuse')
    })

    test('says nothing at all when the document validated', () => {
        expect(issuesNote([])).toBeNull()
    })
})
