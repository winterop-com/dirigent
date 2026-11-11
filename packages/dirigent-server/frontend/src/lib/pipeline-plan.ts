/**
 * What the server said an apply would do, in the words a dialog puts in front of somebody.
 *
 * THE PLAN IS THE APPLY, DRY. `POST /pipelines/$apply?dry_run=true` answers with the same
 * `ApplyResult` the write answers with, so what a reader confirms and what then happens are one
 * request's two readings and cannot disagree. This module is the whole of that reading: a plan
 * in, lines out, and no component decides what `unchanged` means.
 *
 * VALIDATE AND APPLY SHOW THE SAME THING. Validate is the dry run without the button, so the
 * issues a refusal lists are laid out identically whichever of the two asked for them.
 */

import type { JsonMap } from '@/lib/api'
import { counted, type Counted, LABELS } from '@/lib/labels'
import { toYaml } from '@/lib/pipeline-document'
import type {
    ApplyResult,
    DiffSummary,
    Materialized,
    PipelinePlan,
    SourceChanges,
    ValidationIssue,
} from '@/lib/pipelines'

/** How loudly a plan reads: a refusal is not the same news as a version being written. */
export type PlanTone = 'good' | 'quiet' | 'critical'

/** One kind of thing a plan changes or takes away: a row of its list. */
export interface PlanItem {
    label: string
    /** How many of that kind, where the row names them. */
    count?: number
    /** The codes or keys of what the row counts. */
    codes?: readonly string[]
    /** One line of prose under the label. */
    detail?: string
}

/** One plan, rendered. */
export interface PlanView {
    /** The one line at the top of the dialog. */
    headline: string
    tone: PlanTone
    /** What differs from the version the instance holds, one row per kind of change. */
    changes: PlanItem[]
    /** What applying would take away from the instance, one row per kind of thing. */
    retiring: PlanItem[]
    /** What the instance refuses about the document, each addressed at a place in it. */
    issues: ValidationIssue[]
    /** Whether applying is offered at all. */
    applicable: boolean
    /** Whether this writes over a stored version, which is the one plan "no changes" can be said of. */
    updates: boolean
}

/**
 * What an apply that wrote nothing is reported as, which is a line and not a dialog.
 *
 * A confirmation exists to weigh a consequence; there is none here, so the answer is said the
 * way every other action that completed without incident says itself.
 */
export function unchangedNote(plan: PipelinePlan): string {
    return LABELS.editor.apply.unchanged(plan.code)
}

/** What one dry run says, as the dialog lays it out. */
export function planView(result: Pick<ApplyResult, 'plan' | 'triggers' | 'sources'>): PlanView {
    const { plan } = result
    const issues = plan.issues
    const retiring = retiringIn(result)
    switch (plan.action) {
        case 'invalid':
            return {
                headline: LABELS.editor.plan.refuse(plan.code),
                tone: 'critical',
                changes: [],
                retiring: [],
                issues,
                applicable: false,
                updates: false,
            }
        case 'unchanged':
            return {
                headline: LABELS.editor.plan.unchanged(plan.code),
                tone: 'quiet',
                changes: [],
                retiring: [],
                issues,
                applicable: false,
                updates: false,
            }
        case 'create':
            return {
                headline: LABELS.editor.plan.create(plan.code),
                tone: 'good',
                changes: changesIn(plan.diff),
                retiring,
                issues,
                applicable: true,
                updates: false,
            }
        case 'update':
            return {
                headline: LABELS.editor.plan.update(String(plan.next_version ?? 0), plan.code),
                tone: 'good',
                changes: changesIn(plan.diff),
                retiring,
                issues,
                applicable: true,
                updates: true,
            }
    }
}

/** What a dry run says applying would take away, and nothing where it takes nothing. */
export function retiringIn(result: Pick<ApplyResult, 'triggers' | 'sources'>): PlanItem[] {
    const items: PlanItem[] = []
    const said = LABELS.editor.plan.retiring
    named(items, result.sources.removed, said.sources)
    named(items, result.triggers.schedules_removed, said.schedules)
    return items
}

/** What a diff amounts to, one row per kind of change, in the order a reader scans them. */
export function changesIn(diff: DiffSummary | null): PlanItem[] {
    if (diff === null) return []
    const said = LABELS.editor.plan
    const items: PlanItem[] = []
    named(items, diff.steps_added, said.steps_added)
    named(items, diff.steps_removed, said.steps_removed)
    named(items, diff.steps_changed, said.steps_changed)
    if (diff.params_changed) items.push({ label: said.params_changed })
    if (diff.triggers_changed) items.push({ label: said.triggers_changed })
    if (diff.requires_changed) items.push({ label: said.requires_changed })
    if (diff.report_changed) items.push({ label: said.report_changed })
    named(items, diff.alerts_added, said.alerts_added)
    named(items, diff.alerts_removed, said.alerts_removed)
    named(items, diff.alerts_changed, said.alerts_changed)
    if (diff.settings_changed) items.push({ label: said.settings_changed, detail: said.settings_detail })
    return items
}

/** One row counting and naming what a diff put in one of its lists, and nothing where the list is empty. */
function named(items: PlanItem[], codes: readonly string[], label: Counted<string>) {
    if (codes.length === 0) return
    items.push({ label: counted(codes.length, label), count: codes.length, codes })
}

/** The stored document and the one being applied, as the two texts a diff sets side by side. */
export interface DocumentDiff {
    title: string
    before: string
    after: string
}

/**
 * The stored document against the one an update would write, or null where there is no stored
 * one or the two render the same.
 */
export function documentDiff(
    plan: PipelinePlan,
    stored: JsonMap | null,
    applying: JsonMap,
): DocumentDiff | null {
    if (plan.action !== 'update' || stored === null) return null
    const before = toYaml(stored)
    const after = toYaml(applying)
    if (before === after) return null
    return {
        title: LABELS.editor.plan.diff_title(
            String(plan.current_version ?? 0),
            String(plan.next_version ?? 0),
        ),
        before,
        after,
    }
}

/** What an apply did to the triggers, or nothing when it left every one of them alone. */
export function triggerChanges(triggers: Materialized): string[] {
    const lines: string[] = []
    const said = LABELS.editor.plan.materialized
    for (const [what, names] of [
        [said.schedules_created, triggers.schedules_created],
        [said.schedules_updated, triggers.schedules_updated],
        [said.schedules_removed, triggers.schedules_removed],
    ] as const) {
        if (names.length > 0) lines.push(LABELS.editor.plan.change_line(what, names.join(', ')))
    }
    return lines
}

/** What an apply that was carried out amounts to, in one line. */
export function appliedLine(result: ApplyResult): string {
    if (result.version === null) return LABELS.editor.plan.left_as_it_was(result.plan.code)
    return LABELS.editor.plan.at_version(result.plan.code, String(result.version))
}

/** What an apply did to the source rows, or nothing when it left every one of them alone. */
export function sourceChanges(sources: SourceChanges): string[] {
    const lines: string[] = []
    const said = LABELS.editor.plan.materialized
    for (const [what, names] of [
        [said.sources_created, sources.created],
        [said.sources_updated, sources.updated],
        [said.sources_removed, sources.removed],
    ] as const) {
        if (names.length > 0) lines.push(LABELS.editor.plan.change_line(what, names.join(', ')))
    }
    return lines
}

/** What an apply that was carried out says once it lands: the line, and what it did to the triggers and sources. */
export interface AppliedNote {
    line: string
    /** The trigger and source changes joined into one sentence, or undefined when there were none. */
    detail: string | undefined
}

/** What an apply that was carried out amounts to, as the note that follows it. */
export function appliedNote(result: ApplyResult): AppliedNote {
    const changes = [...triggerChanges(result.triggers), ...sourceChanges(result.sources)]
    return { line: appliedLine(result), detail: changes.length === 0 ? undefined : changes.join('; ') }
}

/** What the status bar says about a validation, or null when it found nothing. */
export function issuesNote(issues: ValidationIssue[]): string | null {
    if (issues.length === 0) return null
    return counted(issues.length, LABELS.editor.plan.issues_refuse)(String(issues.length))
}
