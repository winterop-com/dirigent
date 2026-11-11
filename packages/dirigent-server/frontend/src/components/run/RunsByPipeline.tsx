import { useMemo } from 'react'
import { Link, useNavigate } from 'react-router'

import { PipelineRef } from '@/components/PipelineRef'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { DataTable, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { Dot } from '@winterop-com/sokkel-ui/Dot'
import { dotOf, LISTING } from '@/lib/design-system'
import { formatDuration, formatInstant, formatRelative } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import { rowsRead } from '@/lib/paging'
import {
    countsShown,
    pipelineRunsLink,
    type GroupWindow,
    type PipelineRuns,
    type RecentRun,
} from '@/lib/run-summary'
import { statusLabel } from '@/lib/status'

const pipelineOf = (row: PipelineRuns) => row.pipeline

/**
 * The runs of a window, one row per pipeline that ran in it.
 *
 * A row opens the flat list of that pipeline's runs over the same window; a dot in its strip
 * opens that one run.
 */
export function RunsByPipeline({ rows, window }: { rows: readonly PipelineRuns[]; window: GroupWindow }) {
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
            foot={rowsRead(rows.length, LABELS.word.pipeline.count, false)}
        />
    )
}

function summaryColumns(): DataColumn<PipelineRuns>[] {
    return [
        {
            id: 'pipeline',
            header: LABELS.word.pipeline.label,
            width: 'minmax(10rem,2fr)',
            cell: (row) => <PipelineRef code={row.pipeline} name={row.name} />,
        },
        {
            id: 'latest',
            header: LABELS.runs.grouped.latest,
            width: 'minmax(6.5rem,1fr)',
            cell: (row) => <StatusChip status={row.latest.status} />,
        },
        {
            id: 'counts',
            header: LABELS.runs.grouped.counts,
            width: 'minmax(8rem,1fr)',
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
            width: 'minmax(8rem,2fr)',
            cell: (row) => <RecentStrip runs={row.recent} />,
        },
        {
            id: 'last',
            header: LABELS.runs.grouped.last_ran,
            width: 'minmax(6rem,1fr)',
            cell: (row) => (
                <span className="text-xs text-muted-foreground" title={formatInstant(row.latest.created_at)}>
                    {formatRelative(row.latest.created_at)}
                </span>
            ),
        },
        {
            id: 'median',
            header: LABELS.runs.grouped.median,
            width: 'minmax(5rem,1fr)',
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
