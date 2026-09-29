import { describe, expect, test } from 'vitest'

import {
    appliedLine,
    appliedNote,
    changesIn,
    issuesNote,
    planView,
    unchangedNote,
    triggerChanges,
} from '@/lib/pipeline-plan'
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
        watches_created: [],
        watches_updated: [],
        watches_removed: [],
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

    /**
     * NOT EVERY ANSWER IS A DIALOG. An apply of the document the instance already holds has no
     * consequence to weigh, so it is reported the way every other action that completed without
     * incident is, in one line rather than a card with a button that cannot act.
     */
    test('an unchanged apply is a line to report, naming the pipeline and what happened', () => {
        expect(unchangedNote(plan({ action: 'unchanged' }))).toBe(
            'convert-one is already at this document. Nothing was written.',
        )
    })

    test('an invalid document is a refusal, and the issues are what it shows instead', () => {
        const issues = [
            {
                location: 'steps.push.config.method',
                message: 'unknown key',
                code: 'validation.extra_forbidden',
                params: {},
            },
        ]
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
        expect(triggerChanges(materialized({ watches_removed: ['follow'] }))).toEqual([
            'watches removed: follow',
        ])
        expect(triggerChanges(materialized())).toEqual([])
    })

    test('carries what it did to the triggers under the line, and nothing when it left them alone', () => {
        const result: ApplyResult = {
            plan: plan(),
            pipeline_id: 'an-id',
            version: 2,
            dry_run: false,
            triggers: materialized({ schedules_created: ['nightly'], watches_updated: ['follow'] }),
        }
        expect(appliedNote(result)).toEqual({
            line: 'convert-one is at version 2',
            detail: 'schedules created: nightly; watches updated: follow',
        })
        expect(appliedNote({ ...result, triggers: materialized() }).detail).toBeUndefined()
    })
})

describe('what the status bar says about a validation', () => {
    test('counts the issues and says what they mean for an apply', () => {
        expect(
            issuesNote([
                {
                    location: 'steps.push',
                    message: 'no such block',
                    code: 'document.unknown_block',
                    params: {},
                },
            ]),
        ).toBe('1 issue — apply will refuse')
        expect(
            issuesNote([
                {
                    location: 'steps.push',
                    message: 'no such block',
                    code: 'document.unknown_block',
                    params: {},
                },
                {
                    location: 'steps.pull',
                    message: 'no such block',
                    code: 'document.unknown_block',
                    params: {},
                },
            ]),
        ).toBe('2 issues — apply will refuse')
    })

    test('says nothing at all when the document validated', () => {
        expect(issuesNote([])).toBeNull()
    })
})
