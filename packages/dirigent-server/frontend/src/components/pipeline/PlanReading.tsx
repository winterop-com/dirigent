import { counted, LABELS } from '@/lib/labels'
import { DIFF_WORDS, windowWords } from '@/lib/library-words'
import type { DocumentDiff, PlanItem, PlanView } from '@/lib/pipeline-plan'
import type { ValidationIssue } from '@/lib/pipelines'
import { sentenceFor } from '@/lib/wording'
import { Callout } from '@winterop-com/sokkel-ui/Callout'
import { type Consequence, ConsequenceList } from '@winterop-com/sokkel-ui/ConsequenceList'
import { DiffView } from '@winterop-com/sokkel-ui/DiffView'
import { WindowedPane, WindowedPaneButton } from '@winterop-com/sokkel-ui/WindowedPane'

/**
 * One dry run, drawn the one way this app draws one.
 *
 * THE SAME OPERATION READS THE SAME EVERYWHERE. The editor's Validate and Apply and the
 * listing's Apply document are `POST /pipelines/$apply` with and without `dry_run`, so what
 * they say about a plan is this component and not three renderings that can disagree about
 * what `unchanged` means.
 *
 * WHAT IT SAYS IS `lib/pipeline-plan`'s. The headline, whether applying is offered, which
 * changes are worth a row and whether there is a diff to draw are decided there, in plain Node;
 * this lays them out.
 */
/** What one document problem says here: this interface's sentence for its code, else the server's. */
function issueSaid(issue: ValidationIssue): string {
    return sentenceFor(issue.code, issue.params) ?? issue.message
}

/** One row of a plan's list, its codes in mono under the label. */
function consequence(item: PlanItem): Consequence {
    return {
        label: item.label,
        count: item.count,
        detail:
            item.codes === undefined ? (
                item.detail
            ) : (
                <span className="font-mono">{item.codes.join(', ')}</span>
            ),
    }
}

export function PlanReading({ view, diff }: { view: PlanView; diff?: DocumentDiff | null }) {
    return (
        <div className="space-y-3">
            <p className={view.tone === 'critical' ? 'text-sm text-critical' : 'text-sm'}>{view.headline}</p>
            <ConsequenceList
                tone="neutral"
                heading={LABELS.editor.plan.changes_heading}
                items={view.changes.map(consequence)}
            />
            <ConsequenceList
                tone="critical"
                heading={LABELS.editor.plan.retiring.heading}
                items={view.retiring.map(consequence)}
            />
            {diff && <DocumentDiffPane diff={diff} />}
            {view.issues.length > 0 && (
                <Callout
                    tone="critical"
                    title={counted(
                        view.issues.length,
                        LABELS.editor.plan.issues_refuse,
                    )(String(view.issues.length))}
                >
                    <ul className="space-y-0.5 text-xs">
                        {view.issues.map((issue) => (
                            <li key={`${issue.location}:${issue.message}`}>
                                <span className="font-mono">{issue.location}</span>{' '}
                                <span className="text-muted-foreground">{issueSaid(issue)}</span>
                            </li>
                        ))}
                    </ul>
                </Callout>
            )}
            {view.updates &&
                !diff &&
                view.issues.length === 0 &&
                view.changes.length === 0 &&
                view.retiring.length === 0 && (
                    <p className="text-xs text-muted-foreground">{LABELS.editor.plan.no_changes}</p>
                )}
        </div>
    )
}

/**
 * The stored document set against the one being applied: in the dialog its changes with the
 * unchanged runs between them folded, at no height of its own, and every line of it in the window.
 */
function DocumentDiffPane({ diff }: { diff: DocumentDiff }) {
    return (
        <WindowedPane
            title={<span className="font-mono">{diff.title}</span>}
            keepPane
            button="none"
            words={windowWords(diff.title)}
        >
            {(where) =>
                where === 'pane' ? (
                    <DiffView
                        before={diff.before}
                        after={diff.after}
                        title={diff.title}
                        size="sm"
                        actions={<WindowedPaneButton className="text-faint" />}
                        words={DIFF_WORDS}
                    />
                ) : (
                    <DiffView
                        before={diff.before}
                        after={diff.after}
                        size="sm"
                        context={Infinity}
                        className="min-h-0 flex-1"
                        words={DIFF_WORDS}
                    />
                )
            }
        </WindowedPane>
    )
}
