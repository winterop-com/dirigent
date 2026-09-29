import { counted, LABELS } from '@/lib/labels'
import type { PlanView } from '@/lib/pipeline-plan'
import type { ValidationIssue } from '@/lib/pipelines'
import { sentenceFor } from '@/lib/wording'

/**
 * One dry run, drawn the one way this app draws one.
 *
 * THE SAME OPERATION READS THE SAME EVERYWHERE. The editor's Validate and Apply and the
 * listing's Apply document are `POST /pipelines/$apply` with and without `dry_run`, so what
 * they say about a plan is this component and not three renderings that can disagree about
 * what `unchanged` means.
 *
 * WHAT IT SAYS IS `lib/pipeline-plan`'s. The headline, whether applying is offered and which
 * changes are worth a line are decided there, in plain Node; this lays them out.
 */
/** What one document problem says here: this interface's sentence for its code, else the server's. */
function issueSaid(issue: ValidationIssue): string {
    return sentenceFor(issue.code, issue.params) ?? issue.message
}

export function PlanReading({ view }: { view: PlanView }) {
    return (
        <div className="space-y-3">
            <p className={view.tone === 'critical' ? 'text-sm text-critical' : 'text-sm'}>{view.headline}</p>
            {view.changes.length > 0 && (
                <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                    {view.changes.map((line) => (
                        <li key={line}>{line}</li>
                    ))}
                </ul>
            )}
            {view.issues.length > 0 && (
                <div className="space-y-1 rounded-md border border-critical/40 p-2" role="alert">
                    <p className="text-xs font-medium text-critical">
                        {counted(
                            view.issues.length,
                            LABELS.editor.plan.issues_refuse,
                        )(String(view.issues.length))}
                    </p>
                    <ul className="space-y-0.5 text-xs">
                        {view.issues.map((issue) => (
                            <li key={`${issue.location}:${issue.message}`}>
                                <span className="font-mono">{issue.location}</span>{' '}
                                <span className="text-muted-foreground">{issueSaid(issue)}</span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            {view.issues.length === 0 && view.changes.length === 0 && view.tone !== 'critical' && (
                <p className="text-xs text-muted-foreground">{LABELS.editor.plan.no_changes}</p>
            )}
        </div>
    )
}
