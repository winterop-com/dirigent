import { describe, expect, test } from 'vitest'

import {
    appliedLine,
    appliedNote,
    changesIn,
    documentDiff,
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
        requires_changed: false,
        report_changed: false,
        alerts_added: [],
        alerts_removed: [],
        alerts_changed: [],
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

const NO_SOURCES = { created: [], updated: [], removed: [], tokens: [] }

/** A dry run of one plan that takes nothing away. */
function dry(over: Partial<PipelinePlan> = {}) {
    return { plan: plan(over), triggers: materialized(), sources: NO_SOURCES }
}

function materialized(over: Partial<Materialized> = {}): Materialized {
    return {
        schedules_created: [],
        schedules_updated: [],
        schedules_removed: [],
        ...over,
    }
}

describe('what a plan says', () => {
    test('an update names the version applying would write', () => {
        const view = planView(dry())
        expect(view.headline).toBe('Apply writes version 4 of convert-one')
        expect(view.tone).toBe('good')
        expect(view.applicable).toBe(true)
    })

    test('a create says the pipeline is not here yet', () => {
        const view = planView(dry({ action: 'create', current_version: null, next_version: 1 }))
        expect(view.headline).toBe('Apply creates convert-one at version 1')
        expect(view.applicable).toBe(true)
    })

    test('an unchanged document offers no apply, because applying it writes nothing', () => {
        const view = planView(dry({ action: 'unchanged' }))
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
            'convert-one already matches this document. Nothing was written.',
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
        const view = planView(dry({ action: 'invalid', next_version: null, diff: null, issues }))
        expect(view.headline).toBe('Applying convert-one will be refused')
        expect(view.tone).toBe('critical')
        expect(view.applicable).toBe(false)
        expect(view.issues).toEqual(issues)
        expect(view.changes).toEqual([])
    })
})

describe('what a diff amounts to', () => {
    test('is a row per kind of change, counting and naming the steps in each', () => {
        expect(
            changesIn(
                diff({ steps_added: ['as_csv'], steps_changed: ['parse', 'report'], params_changed: true }),
            ),
        ).toEqual([
            { label: 'Step added', count: 1, codes: ['as_csv'] },
            { label: 'Steps changed', count: 2, codes: ['parse', 'report'] },
            { label: 'Parameter schema changed' },
        ])
    })

    test('is nothing when the two definitions are the same in every respect', () => {
        expect(changesIn(diff())).toEqual([])
    })

    test('is nothing when the plan carried no diff at all', () => {
        expect(changesIn(null)).toEqual([])
    })

    test('names the settings change in the terms the server summarises it in', () => {
        expect(changesIn(diff({ settings_changed: true, triggers_changed: true }))).toEqual([
            { label: 'Triggers changed' },
            {
                label: 'Settings changed',
                detail: 'Name, description, tags, concurrency, priority or importance',
            },
        ])
    })

    test('names the alert rules the document added, removed and changed', () => {
        expect(
            changesIn(
                diff({
                    alerts_added: ['page-ops'],
                    alerts_removed: ['old', 'older'],
                    alerts_changed: ['log'],
                }),
            ),
        ).toEqual([
            { label: 'Alert rule added', count: 1, codes: ['page-ops'] },
            { label: 'Alert rules removed', count: 2, codes: ['old', 'older'] },
            { label: 'Alert rule changed', count: 1, codes: ['log'] },
        ])
    })

    test('names a report and a requirement that changed', () => {
        expect(changesIn(diff({ report_changed: true, requires_changed: true }))).toEqual([
            { label: 'Requirements changed' },
            { label: 'Report changed' },
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
            sources: NO_SOURCES,
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
            sources: NO_SOURCES,
        }
        expect(appliedLine(result)).toBe('convert-one was left as it was')
    })

    test('lists what it did to the triggers, and nothing when it left them alone', () => {
        expect(
            triggerChanges(materialized({ schedules_created: ['nightly'], schedules_updated: ['hourly'] })),
        ).toEqual(['schedules created: nightly', 'schedules updated: hourly'])
        expect(triggerChanges(materialized({ schedules_removed: ['hourly'] }))).toEqual([
            'schedules removed: hourly',
        ])
        expect(triggerChanges(materialized())).toEqual([])
    })

    test('carries what it did to the triggers under the line, and nothing when it left them alone', () => {
        const result: ApplyResult = {
            plan: plan(),
            pipeline_id: 'an-id',
            version: 2,
            dry_run: false,
            triggers: materialized({ schedules_created: ['nightly'], schedules_updated: ['hourly'] }),
            sources: NO_SOURCES,
        }
        expect(appliedNote(result)).toEqual({
            line: 'convert-one is at version 2',
            detail: 'schedules created: nightly; schedules updated: hourly',
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
        ).toBe('1 issue — applying will be refused')
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
        ).toBe('2 issues — applying will be refused')
    })

    test('says nothing at all when the document validated', () => {
        expect(issuesNote([])).toBeNull()
    })
})

describe('what an apply would take away', () => {
    test('counts and names each source and schedule a document stopped declaring', () => {
        const view = planView({
            plan: plan(),
            triggers: materialized({ schedules_removed: ['nightly'] }),
            sources: { ...NO_SOURCES, removed: ['orders', 'refunds'] },
        })
        expect(view.retiring).toEqual([
            { label: 'Sources, with their inputs and their tokens', count: 2, codes: ['orders', 'refunds'] },
            { label: 'Schedule', count: 1, codes: ['nightly'] },
        ])
    })

    test('is nothing where it takes nothing, and on a plan that writes nothing', () => {
        expect(planView(dry()).retiring).toEqual([])
        const refused = planView({
            plan: plan({ action: 'invalid' }),
            triggers: materialized({ schedules_removed: ['nightly'] }),
            sources: NO_SOURCES,
        })
        expect(refused.retiring).toEqual([])
    })

    test('is said in the past tense once it has been done', () => {
        const result: ApplyResult = {
            plan: plan(),
            pipeline_id: 'an-id',
            version: 2,
            dry_run: false,
            triggers: materialized({ schedules_removed: ['nightly'] }),
            sources: { ...NO_SOURCES, created: ['orders'], removed: ['refunds'] },
        }
        expect(appliedNote(result).detail).toBe(
            'schedules removed: nightly; sources created: orders; sources removed: refunds',
        )
    })
})

describe('whether a plan can be said to change nothing', () => {
    test('is only where it writes over a stored version', () => {
        expect(planView(dry({ action: 'update' })).updates).toBe(true)
        expect(planView(dry({ action: 'create' })).updates).toBe(false)
        expect(planView(dry({ action: 'unchanged' })).updates).toBe(false)
        expect(planView(dry({ action: 'invalid' })).updates).toBe(false)
    })
})

describe('the stored document set against the one being applied', () => {
    const stored = { code: 'convert-one', steps: { one: { block: 'transform.jq' } } }

    test('is the two documents as the source pane renders them, titled by the versions', () => {
        const applying = { code: 'convert-one', steps: { one: { block: 'transform.jq', name: 'One' } } }
        const said = documentDiff(plan(), stored, applying)
        expect(said?.title).toBe('v3 → v4')
        expect(said?.before).toContain('block: transform.jq')
        expect(said?.before).not.toContain('name: One')
        expect(said?.after).toContain('name: One')
    })

    test('is nothing where the two render the same', () => {
        expect(documentDiff(plan(), stored, { ...stored })).toBeNull()
    })

    test('is nothing where there is no stored version to write over', () => {
        expect(documentDiff(plan({ action: 'create' }), stored, { code: 'convert-one' })).toBeNull()
        expect(documentDiff(plan(), null, stored)).toBeNull()
    })
})
