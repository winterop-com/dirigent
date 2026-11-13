import { useEffect, useState } from 'react'

import { DescriptionList } from '@winterop-com/sokkel-ui/DescriptionList'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { ReportDocumentPane } from '@/components/run/ReportDocument'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { ApiError, type Problem } from '@/lib/api'
import { readReportDocument, renderedText, type RenderedText, type ReportDocument } from '@/lib/artifacts'
import { formatDuration } from '@/lib/format'
import { Group } from '@winterop-com/sokkel-ui/Group'
import { LABELS } from '@/lib/labels'
import { itemsNote, type AttemptOut, type RunReport } from '@/lib/runs'
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
 * MARKDOWN GOES THROUGH `Description`. The renderer is its own chunk and this is the only pane on
 * the run screen that draws prose, so a reader who never opens this tab never fetches it.
 *
 * A STEP'S TEXT IS NOT THE RUN'S REPORT. A `report.render` step hands its text on as output,
 * and a document that declares no `report:` renders no document of its own, so the tab offers
 * the step's text behind a control and says what makes it the report: `report: {from: <step>}`.
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
    attempts,
}: {
    runId: string
    /** Whether the run has reached a state nothing will move it out of. */
    settled: boolean
    /** The structured summary, or null while it is being read. */
    report: RunReport | null
    /** Why the summary could not be read, or null. */
    problem: Problem | null
    /** The run's attempts, which is where a rendering step's text is read from. */
    attempts: readonly AttemptOut[]
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

    if (found.document === null) {
        return <Summary report={report} problem={problem} rendered={renderedText(attempts)} />
    }

    return <ReportDocumentPane document={found.document} />
}

/**
 * What a run without a report document says about itself, which is what the API summarises.
 *
 * The second sentence names the document key, because declaring one is not a gesture anywhere
 * on this screen.
 */
function Summary({
    report,
    problem,
    rendered,
}: {
    report: RunReport | null
    problem: Problem | null
    rendered: RenderedText | null
}) {
    const items = report === null ? null : itemsNote(report.items_total, report.items_failed)
    return (
        <div className="flex flex-col gap-4 p-4">
            {rendered === null ? (
                <p className="text-sm text-muted-foreground">{LABELS.runs.report_missing}</p>
            ) : (
                <StepRendered rendered={rendered} />
            )}
            <Group title={LABELS.word.summary}>
                {problem !== null ? (
                    <p className="text-xs text-muted-foreground">{said(problem)}</p>
                ) : report === null ? (
                    <p className="text-xs text-muted-foreground">{LABELS.shell.reading}</p>
                ) : (
                    <>
                        <DescriptionList
                            termWidth="auto"
                            size="sm"
                            items={[
                                {
                                    term: LABELS.runs.fact.took,
                                    value:
                                        report.duration_ms === null
                                            ? null
                                            : formatDuration(report.duration_ms),
                                    numeric: true,
                                },
                                ...(items === null ? [] : [{ term: LABELS.runs.fact.items, value: items }]),
                            ]}
                        />
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
            </Group>
        </div>
    )
}

/** What a run with no report document says when one of its steps rendered text, and the text behind a control. */
function StepRendered({ rendered }: { rendered: RenderedText }) {
    const [shown, setShown] = useState(false)
    const words = LABELS.runs.report_rendered_by_step
    return (
        <div className="flex flex-col gap-2">
            <p className="text-sm text-muted-foreground">
                {words.before} <span className="font-mono text-foreground">{rendered.step}</span>{' '}
                {words.after}{' '}
                <span className="font-mono text-foreground">{`report: {from: ${rendered.step}}`}</span>{' '}
                {words.hint_after}
            </p>
            <Button
                variant="outline"
                size="sm"
                className="w-fit"
                aria-expanded={shown}
                onClick={() => {
                    setShown((was) => !was)
                }}
            >
                {shown ? LABELS.runs.report_hide_step : LABELS.runs.report_show_step}
            </Button>
            {shown && <ReportDocumentPane document={{ id: null, markdown: rendered.text }} capped />}
        </div>
    )
}
