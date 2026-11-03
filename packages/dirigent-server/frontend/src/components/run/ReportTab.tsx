import { useEffect, useState } from 'react'

import { Fact, Section } from '@/components/run/Panel'
import { ReportDocumentPane } from '@/components/run/ReportDocument'
import { StatusChip } from '@/components/run/StatusChip'
import { ApiError, type Problem } from '@/lib/api'
import { readReportDocument, type ReportDocument } from '@/lib/artifacts'
import { formatDuration } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import { itemsNote, type RunReport } from '@/lib/runs'
import { said } from '@/lib/refusal'

/**
 * The run's own account of itself: the document it rendered when it settled, or the summary.
 *
 * THE DOCUMENT IS THE RUN'S, NOT THIS SCREEN'S. A pipeline document declaring a `report:`
 * section renders one markdown document per run inside the transaction that settles the run,
 * and this reads it back. A document that declares none renders nothing, and what stands in
 * its place is the structured summary `GET /runs/{id}/$report` assembles from queries.
 *
 * IT IS READ ONCE THE RUN IS TERMINAL AND NEVER BEFORE. The document does not exist until the
 * run settles, so the read is keyed on that transition -- the run's state moves live over the
 * event stream, so a run that settles while this tab is open reads its document then.
 *
 * MARKDOWN GOES THROUGH `Description`. The lexer is its own chunk and this is the only pane on
 * the run screen that draws prose, so a reader who never opens this tab never fetches it.
 *
 * A DOCUMENT IS WIDER THAN THE PANEL. The panel is a column a few hundred pixels across and a
 * report is a page: it opens in the window every pane holding more than it can show offers, at
 * a reading measure, and the raw markdown is a link away for whoever wants the file itself.
 */
export function ReportTab({
    runId,
    settled,
    report,
    problem,
}: {
    runId: string
    /** Whether the run has reached a state nothing will move it out of. */
    settled: boolean
    /** The structured summary, or null while it is being read. */
    report: RunReport | null
    /** Why the summary could not be read, or null. */
    problem: Problem | null
}) {
    // Keyed by the run it was read for, so opening another run shows its own reading rather
    // than the last one's document for a frame. Nothing here is cleared from inside an effect.
    const [read, setRead] = useState<{
        of: string
        document: ReportDocument | null
        refusal: Problem | null
    } | null>(null)

    useEffect(() => {
        if (!settled) return
        let cancelled = false
        void readReportDocument(runId).then(
            (found) => {
                if (!cancelled) setRead({ of: runId, document: found, refusal: null })
            },
            (error: unknown) => {
                if (!cancelled) {
                    setRead({
                        of: runId,
                        document: null,
                        refusal: error instanceof ApiError ? error.problem : null,
                    })
                }
            },
        )
        return () => {
            cancelled = true
        }
    }, [runId, settled])

    const found = read?.of === runId ? read : null

    if (!settled) {
        return <p className="p-4 text-sm text-muted-foreground">{LABELS.runs.report_pending}</p>
    }

    if (found !== null && found.refusal !== null) {
        return <p className="p-4 text-sm text-muted-foreground">{said(found.refusal)}</p>
    }

    if (found === null) {
        return <p className="p-4 text-sm text-muted-foreground">{LABELS.shell.reading}</p>
    }

    if (found.document === null) return <Summary report={report} problem={problem} />

    return <ReportDocumentPane document={found.document} />
}

/**
 * What a run without a report document says about itself, which is what the API summarises.
 *
 * The second sentence names the document key, because declaring one is not a gesture anywhere
 * on this screen.
 */
function Summary({ report, problem }: { report: RunReport | null; problem: Problem | null }) {
    const items = report === null ? null : itemsNote(report.items_total, report.items_failed)
    return (
        <div className="flex flex-col gap-4 p-4">
            <p className="text-sm text-muted-foreground">{LABELS.runs.report_missing}</p>
            <Section title={LABELS.word.summary}>
                {problem !== null ? (
                    <p className="text-xs text-muted-foreground">{said(problem)}</p>
                ) : report === null ? (
                    <p className="text-xs text-muted-foreground">{LABELS.shell.reading}</p>
                ) : (
                    <>
                        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                            <Fact term={LABELS.runs.fact.took} detail={formatDuration(report.duration_ms)} />
                            {items !== null && <Fact term={LABELS.runs.fact.items} detail={items} />}
                        </dl>
                        <ul className="mt-2 space-y-1">
                            {report.steps.map((step) => (
                                <li key={step.step} className="flex items-center gap-2">
                                    <StatusChip status={step.outcome} />
                                    <span className="truncate text-sm">{step.step}</span>
                                    {step.warnings > 0 && (
                                        <span className="text-xs text-warning">
                                            {LABELS.runs.step_warned(String(step.warnings))}
                                        </span>
                                    )}
                                    <span className="ml-auto shrink-0 text-xs text-faint">
                                        {formatDuration(step.duration_ms)}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    </>
                )}
            </Section>
        </div>
    )
}
