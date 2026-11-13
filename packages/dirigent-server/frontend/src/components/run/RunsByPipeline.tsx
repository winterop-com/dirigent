import { useMemo, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router'

import { Instant } from '@/components/Instant'
import { PipelineRef } from '@/components/PipelineRef'
import { refusedTable } from '@/components/Refusal'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { DataTable, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { Dot } from '@winterop-com/sokkel-ui/Dot'
import type { Problem } from '@/lib/api'
import { countWords, LISTING } from '@/lib/library-words'
import { formatDuration, formatInstant } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import {
    countsShown,
    pipelineRunsLink,
    type GroupWindow,
    type PipelineRuns,
    type RecentRun,
} from '@/lib/run-summary'
import { dotOf, statusLabel } from '@/lib/status'

const pipelineOf = (row: PipelineRuns) => row.pipeline

/**
 * The runs of a window, one row per pipeline that ran in it.
 *
 * A row opens the flat list of that pipeline's runs over the same window; a dot in its strip
 * opens that one run. The screen's `search` and `toolbar` stand in the table's bar.
 */
export function RunsByPipeline({
    rows,
    window,
    search,
    toolbar,
    loading,
    problem,
    onRetry,
    empty,
}: {
    rows: readonly PipelineRuns[]
    window: GroupWindow
    search: ReactNode
    toolbar: ReactNode
    loading: boolean
    /** The refusal of the read the rows come from, drawn in their place. */
    problem: Problem | null
    onRetry: () => void
    /** What the table says with no rows. */
    empty: ReactNode
}) {
    const navigate = useNavigate()
    const columns = useMemo(() => summaryColumns(), [])
    return (
        <DataTable
            {...LISTING}
            rowHeight="auto"
            columns={columns}
            rows={rows}
            rowKey={pipelineOf}
            onOpen={(row) => void navigate(pipelineRunsLink(row.pipeline, window))}
            search={search}
            toolbar={toolbar}
            loading={loading}
            {...refusedTable(problem, onRetry, countWords(LABELS.word.pipeline.count))}
            empty={empty}
        />
    )
}

function summaryColumns(): DataColumn<PipelineRuns>[] {
    return [
        {
            id: 'pipeline',
            header: LABELS.word.pipeline.label,
            width: 'minmax(15rem,2fr)',
            stackTitle: 'free',
            cell: (row) => <PipelineRef code={row.pipeline} name={row.name} />,
        },
        {
            id: 'latest',
            header: LABELS.runs.grouped.latest,
            width: 'minmax(6rem,1fr)',
            cell: (row) => <StatusChip status={row.latest.status} />,
        },
        {
            id: 'counts',
            header: LABELS.runs.grouped.counts,
            width: 'minmax(7rem,1fr)',
            cell: (row) => (
                <span className="flex items-center gap-3 text-xs whitespace-nowrap">
                    {countsShown(row.counts).map(({ status, runs }) => {
                        const said = LABELS.runs.node_item_count(String(runs), statusLabel(status))
                        return (
                            <span
                                key={status}
                                className="inline-flex items-center gap-1.5 font-mono"
                                title={said}
                                aria-label={said}
                            >
                                <Dot {...dotOf({ status }, 'never')} />
                                {runs}
                            </span>
                        )
                    })}
                </span>
            ),
        },
        {
            id: 'recent',
            header: LABELS.runs.grouped.recent,
            width: 'minmax(4.5rem,2fr)',
            cell: (row) => <RecentStrip runs={row.recent} />,
        },
        {
            id: 'last',
            header: LABELS.runs.grouped.last_ran,
            width: 'minmax(4rem,1fr)',
            cell: (row) => <Instant className="text-xs text-muted-foreground" at={row.latest.created_at} />,
        },
        {
            id: 'median',
            header: LABELS.runs.grouped.median,
            width: 'minmax(3.5rem,1fr)',
            align: 'end',
            cell: (row) =>
                row.median_duration_ms === null ? null : (
                    <span className="font-mono text-xs">{formatDuration(row.median_duration_ms)}</span>
                ),
        },
    ]
}

/**
 * A pipeline's most recent runs as one dot each, oldest left and newest right.
 *
 * Where the cell is narrower than the strip, the oldest are the ones cut: the strip is laid out
 * from its right end, newest first, so what overflows is on the left.
 */
function RecentStrip({ runs }: { runs: readonly RecentRun[] }) {
    return (
        <span
            className="flex w-max max-w-full min-w-0 flex-row-reverse items-center overflow-hidden"
            data-testid="recent-runs"
        >
            {runs.toReversed().map((run) => {
                const said = LABELS.runs.grouped.dot(statusLabel(run.status), formatInstant(run.created_at))
                return (
                    <Link
                        key={run.id}
                        to={`/runs/${run.id}`}
                        className="flex shrink-0 items-center rounded-sm p-0.5 hover:bg-muted"
                        title={said}
                        aria-label={said}
                        data-status={run.status}
                        onClick={(event) => {
                            event.stopPropagation()
                        }}
                    >
                        <Dot {...dotOf({ status: run.status }, 'never')} className="pointer-events-none" />
                    </Link>
                )
            })}
        </span>
    )
}
