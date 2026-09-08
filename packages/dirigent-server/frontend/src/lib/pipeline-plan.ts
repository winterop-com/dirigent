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

import type { ApplyResult, DiffSummary, Materialized, PipelinePlan, ValidationIssue } from '@/lib/pipelines'

/** How loudly a plan reads: a refusal is not the same news as a version being written. */
export type PlanTone = 'good' | 'quiet' | 'critical'

/** One plan, rendered. */
export interface PlanView {
    /** The one line at the top of the dialog. */
    headline: string
    tone: PlanTone
    /** What differs from the version the instance holds, one line per kind of change. */
    changes: string[]
    /** What the instance refuses about the document, each addressed at a place in it. */
    issues: ValidationIssue[]
    /** Whether applying is offered at all. */
    applicable: boolean
}

/** What one plan says, as the dialog lays it out. */
export function planView(plan: PipelinePlan): PlanView {
    const issues = plan.issues
    switch (plan.action) {
        case 'invalid':
            return {
                headline: `Apply will refuse ${plan.code}`,
                tone: 'critical',
                changes: [],
                issues,
                applicable: false,
            }
        case 'unchanged':
            return {
                headline: `Apply writes nothing — ${plan.code} is already at this document`,
                tone: 'quiet',
                changes: [],
                issues,
                applicable: false,
            }
        case 'create':
            return {
                headline: `Apply creates ${plan.code} at version 1`,
                tone: 'good',
                changes: changesIn(plan.diff),
                issues,
                applicable: true,
            }
        case 'update':
            return {
                headline: `Apply writes version ${String(plan.next_version ?? 0)} of ${plan.code}`,
                tone: 'good',
                changes: changesIn(plan.diff),
                issues,
                applicable: true,
            }
    }
}

/** What a diff amounts to, one line per kind of change, in the order a reader scans them. */
export function changesIn(diff: DiffSummary | null): string[] {
    if (diff === null) return []
    const lines: string[] = []
    if (diff.steps_added.length > 0) lines.push(`steps added: ${diff.steps_added.join(', ')}`)
    if (diff.steps_removed.length > 0) lines.push(`steps removed: ${diff.steps_removed.join(', ')}`)
    if (diff.steps_changed.length > 0) lines.push(`steps changed: ${diff.steps_changed.join(', ')}`)
    if (diff.params_changed) lines.push('the parameter schema changed')
    if (diff.triggers_changed) lines.push('the triggers changed')
    if (diff.settings_changed) lines.push('the name, description, or concurrency policy changed')
    return lines
}

/** What an apply did to the triggers, or nothing when it left every one of them alone. */
export function triggerChanges(triggers: Materialized): string[] {
    const lines: string[] = []
    for (const [what, names] of [
        ['schedules created', triggers.schedules_created],
        ['schedules updated', triggers.schedules_updated],
        ['schedules removed', triggers.schedules_removed],
        ['webhooks created', triggers.webhooks_created],
        ['webhooks updated', triggers.webhooks_updated],
        ['webhooks removed', triggers.webhooks_removed],
    ] as const) {
        if (names.length > 0) lines.push(`${what}: ${names.join(', ')}`)
    }
    return lines
}

/** What an apply that was carried out amounts to, in one line. */
export function appliedLine(result: ApplyResult): string {
    if (result.version === null) return `${result.plan.code} was left as it was`
    return `${result.plan.code} is at version ${String(result.version)}`
}

/** What the status bar says about a validation, or null when it found nothing. */
export function issuesNote(issues: ValidationIssue[]): string | null {
    if (issues.length === 0) return null
    return `${String(issues.length)} issue${issues.length === 1 ? '' : 's'} — apply will refuse`
}
