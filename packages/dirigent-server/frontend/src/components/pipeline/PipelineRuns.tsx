import { useCallback } from 'react'
import { Link } from 'react-router'

import { Panel } from '@/components/ds/Panel'
import { TextLink } from '@winterop-com/sokkel-ui/TextLink'
import { Instant } from '@/components/Instant'
import { ReportDocumentPane } from '@/components/run/ReportDocument'
import { StatusChip } from '@/components/run/StatusChip'
import { useRead } from '@/hooks/use-read'
import type { Problem } from '@/lib/api'
import { readReportDocument } from '@/lib/artifacts'
import { elapsedBetween, formatDuration, formatInstant, formatRelative } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import { said } from '@/lib/refusal'
import { EVERY_RUN, runReportLink, runsLink, startedAs, type RunOut } from '@/lib/runs'

/** How many runs the recent-runs panel draws; the runs screen holds the rest. */
export const RECENT_ROWS = 8

/** How many settled runs the report panel reads: the latest, and the ones linked under it. */
export const REPORT_RUNS = 6

/**
 * The pipeline's newest runs, one line each, and the way to the runs screen narrowed to it.
 *
 * Each line is the state, what started the run, how long it took, and when; the line is the
 * link to the run's own screen.
 */
export function RecentRuns({
    pipeline,
    runs,
    problem,
    className,
}: {
    pipeline: string
    /** The newest runs, or null while they are being read. */
    runs: readonly RunOut[] | null
    problem: Problem | null
    className?: string
}) {
    return (
        <Panel
            title={LABELS.pipelines.page.recent_runs}
            inset={false}
            className={className}
            aside={
                <TextLink
                    variant="aside"
                    href={runsLink({ ...EVERY_RUN, pipeline })}
                    className="text-xs font-normal"
                >
                    {LABELS.pipelines.page.all_runs}
                </TextLink>
            }
        >
            {problem !== null ? (
                <p className="p-4 text-sm text-muted-foreground">{said(problem)}</p>
            ) : runs === null ? (
                <p className="p-4 text-sm text-muted-foreground">{LABELS.shell.reading}</p>
            ) : runs.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">{LABELS.pipelines.page.no_runs}</p>
            ) : (
                <div data-testid="pipeline-runs">
                    {runs.map((run) => (
                        <RunLine key={run.id} run={run} />
                    ))}
                </div>
            )}
        </Panel>
    )
}

/** One run on one line: its state, what started it, how long it took, and when. */
function RunLine({ run }: { run: RunOut }) {
    const took = elapsedBetween(run.started_at, run.finished_at)
    const started = startedAs(run)
    return (
        <Link
            to={`/runs/${run.id}`}
            className="flex min-w-0 items-center gap-4 border-t border-border px-4 py-2 first:border-t-0 hover:bg-muted"
        >
            <span className="w-36 shrink-0">
                <StatusChip status={run.status} />
            </span>
            <span
                className="hidden min-w-0 flex-1 truncate text-xs sm:block"
                title={started.recorded ?? undefined}
            >
                {started.said}
            </span>
            <span className="ml-auto w-16 shrink-0 text-right font-mono text-xs text-muted-foreground">
                {took === null ? null : formatDuration(took)}
            </span>
            <Instant
                className="w-18 shrink-0 text-right text-xs text-muted-foreground"
                at={run.started_at ?? run.created_at}
            />
        </Link>
    )
}

/**
 * The latest settled run's report document, the run it came from, and links to the reports of
 * the settled runs before it.
 *
 * Drawn only once there is a settled run to read: a pipeline that declares a report and has
 * never settled a run has nothing in this panel to show.
 */
export function LatestReport({ runs, className }: { runs: readonly RunOut[]; className?: string }) {
    const [latest, ...earlier] = runs
    const read = useRead(useCallback(() => readReportDocument(latest.id), [latest.id]))
    const at = latest.finished_at ?? latest.started_at ?? latest.created_at
    return (
        <Panel
            title={LABELS.pipelines.page.report}
            inset={false}
            className={className}
            aside={
                <TextLink
                    variant="aside"
                    href={runReportLink(latest.id)}
                    title={formatInstant(at)}
                    className="text-xs font-normal"
                >
                    {LABELS.pipelines.page.report_run(formatRelative(at))}
                </TextLink>
            }
        >
            <div data-testid="pipeline-report">
                {read.problem !== null ? (
                    <p className="p-4 text-sm text-muted-foreground">{said(read.problem)}</p>
                ) : !read.read ? (
                    <p className="p-4 text-sm text-muted-foreground">{LABELS.shell.reading}</p>
                ) : read.value === null ? (
                    <p className="p-4 text-sm text-muted-foreground">{LABELS.pipelines.page.report_none}</p>
                ) : (
                    <ReportDocumentPane document={read.value} capped />
                )}
            </div>
            {earlier.length > 0 && (
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-border px-4 py-2.5 text-xs">
                    <span className="text-muted-foreground">{LABELS.pipelines.page.earlier_reports}</span>
                    {earlier.map((run) => {
                        const when = run.finished_at ?? run.started_at ?? run.created_at
                        return (
                            <TextLink
                                key={run.id}
                                variant="inline"
                                href={runReportLink(run.id)}
                                title={formatInstant(when)}
                            >
                                {formatRelative(when)}
                            </TextLink>
                        )
                    })}
                </div>
            )}
        </Panel>
    )
}
