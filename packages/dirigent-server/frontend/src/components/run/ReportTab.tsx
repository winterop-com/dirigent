import { useEffect, useState } from 'react'

import { Description } from '@/components/Description'
import { Fact, Section } from '@/components/run/Panel'
import { StatusChip } from '@/components/run/StatusChip'
import { WindowedPane } from '@/components/WindowedPane'
import { useApiPrefix } from '@/hooks/use-api-prefix'
import { ApiError, type Problem } from '@/lib/api'
import { artifactUrl, readReportDocument, type ReportDocument } from '@/lib/artifacts'
import { formatDuration } from '@/lib/format'
import { itemsNote, type RunReport } from '@/lib/runs'
import { cn } from '@/lib/utils'

/** What the window is titled and what a saved file is called. */
const DOCUMENT_NAME = 'report.md'

/**
 * How the document is set in the window: prose at a reading measure, tables the whole width.
 *
 * The markdown component draws one flat column of blocks and knows nothing about a measure, so
 * the measure is put on the blocks that are read as sentences. A table is not one of them: it
 * is drawn in its own scrolling box, and what a window buys it is the room not to scroll.
 */
const READING =
    '[&_p]:mx-auto [&_p]:max-w-[68ch] [&_ul]:mx-auto [&_ul]:max-w-[68ch] [&_ol]:mx-auto [&_ol]:max-w-[68ch] [&_pre]:mx-auto [&_pre]:max-w-[68ch] [&_blockquote]:mx-auto [&_blockquote]:max-w-[68ch]'

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
    const prefix = useApiPrefix()

    useEffect(() => {
        if (!settled) return
        let cancelled = false
        void readReportDocument(runId).then(
            (found) => {
                if (!cancelled) setRead({ of: runId, document: found, refusal: null })
            },
            (error: unknown) => {
                if (!cancelled) {
                    setRead({ of: runId, document: null, refusal: error instanceof ApiError ? error.problem : null })
                }
            },
        )
        return () => {
            cancelled = true
        }
    }, [runId, settled])

    const found = read?.of === runId ? read : null

    if (!settled) {
        return (
            <p className="text-muted-foreground p-4 text-sm">The report is written when this run settles.</p>
        )
    }

    if (found !== null && found.refusal !== null) {
        return <p className="text-muted-foreground p-4 text-sm">{found.refusal.detail}</p>
    }

    if (found === null) {
        return <p className="text-muted-foreground p-4 text-sm">Reading the report.</p>
    }

    if (found.document === null) return <Summary report={report} problem={problem} />

    const markdown = found.document.markdown
    return (
        <WindowedPane
            name={DOCUMENT_NAME}
            className="flex flex-col gap-3 p-4"
            windowed={
                <div className={cn('min-h-0 w-full flex-1 overflow-y-auto', READING)}>
                    <Description text={markdown} ink="body" />
                </div>
            }
        >
            <Description text={markdown} ink="body" />
            {prefix !== null && (
                <a
                    className="text-primary-ink w-fit text-xs hover:underline"
                    href={artifactUrl(prefix, found.document.id)}
                    download={DOCUMENT_NAME}
                    rel="noopener"
                >
                    Download the markdown
                </a>
            )}
        </WindowedPane>
    )
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
            <p className="text-muted-foreground text-sm">
                This run rendered no report document. A pipeline document declares one under its report key.
            </p>
            <Section title="Summary">
                {problem !== null ? (
                    <p className="text-muted-foreground text-xs">{problem.detail}</p>
                ) : report === null ? (
                    <p className="text-muted-foreground text-xs">Reading the summary.</p>
                ) : (
                    <>
                        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                            <Fact term="took" detail={formatDuration(report.duration_ms)} />
                            {items !== null && <Fact term="items" detail={items} />}
                        </dl>
                        <ul className="mt-2 space-y-1">
                            {report.steps.map((step) => (
                                <li key={step.step} className="flex items-center gap-2">
                                    <StatusChip status={step.outcome} />
                                    <span className="truncate text-sm">{step.step}</span>
                                    {step.warnings > 0 && (
                                        <span className="text-warning text-xs">{step.warnings} warned</span>
                                    )}
                                    <span className="text-faint ml-auto shrink-0 text-xs">
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
