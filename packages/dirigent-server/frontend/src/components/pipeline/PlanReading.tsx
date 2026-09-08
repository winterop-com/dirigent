import type { PlanView } from '@/lib/pipeline-plan'

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
export function PlanReading({ view }: { view: PlanView }) {
    return (
        <div className="space-y-3">
            <p className={view.tone === 'critical' ? 'text-critical text-sm' : 'text-sm'}>{view.headline}</p>
            {view.changes.length > 0 && (
                <ul className="text-muted-foreground list-disc space-y-0.5 pl-4 text-xs">
                    {view.changes.map((line) => (
                        <li key={line}>{line}</li>
                    ))}
                </ul>
            )}
            {view.issues.length > 0 && (
                <div className="border-critical/40 space-y-1 rounded-md border p-2" role="alert">
                    <p className="text-critical text-xs font-medium">
                        {view.issues.length} issue{view.issues.length === 1 ? '' : 's'} — apply will refuse
                    </p>
                    <ul className="space-y-0.5 text-xs">
                        {view.issues.map((issue) => (
                            <li key={`${issue.location}:${issue.message}`}>
                                <span className="font-mono">{issue.location}</span>{' '}
                                <span className="text-muted-foreground">{issue.message}</span>
                            </li>
                        ))}
                    </ul>
                </div>
            )}
            {view.issues.length === 0 && view.changes.length === 0 && view.tone !== 'critical' && (
                <p className="text-muted-foreground text-xs">No changes from the stored version.</p>
            )}
        </div>
    )
}
