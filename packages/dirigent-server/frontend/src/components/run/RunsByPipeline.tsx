import { useMemo } from 'react'
import { Link, useNavigate } from 'react-router'

import { ListTable, type Column } from '@/components/list/ListTable'
import { PipelineRef } from '@/components/PipelineRef'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { Dot } from '@winterop-com/sokkel-ui/Dot'
import { dotOf } from '@/lib/design-system'
import { formatDuration, formatInstant, formatRelative } from '@/lib/format'
import { LABELS } from '@/lib/labels'
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
export function RunsByPipeline({
    rows,
    window,
    reading,
}: {
    rows: readonly PipelineRuns[]
    window: GroupWindow
    reading: boolean
}) {
    const navigate = useNavigate()
    const columns = useMemo(() => summaryColumns(), [])
    return (
        <ListTable
            columns={columns}
            rows={rows}
            rowKey={pipelineOf}
            onSelect={(row) => void navigate(pipelineRunsLink(row.pipeline, window))}
            reading={reading}
            next={null}
            onMore={() => undefined}
            noun={LABELS.word.pipeline.count}
        />
    )
}

function summaryColumns(): Column<PipelineRuns>[] {
    return [
        {
            id: 'pipeline',
            header: LABELS.word.pipeline.label,
            kind: 'title',
            cell: (row) => <PipelineRef code={row.pipeline} name={row.name} />,
        },
        {
            id: 'latest',
            header: LABELS.runs.grouped.latest,
            cell: (row) => <StatusChip dot status={row.latest.status} />,
        },
        {
            id: 'counts',
            header: LABELS.runs.grouped.counts,
            className: 'text-xs',
            cell: (row) => (
                <span className="flex items-center gap-3 whitespace-nowrap">
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
            kind: 'prose',
            cell: (row) => <RecentStrip runs={row.recent} />,
        },
        {
            id: 'last',
            header: LABELS.runs.grouped.last_ran,
            className: 'text-xs',
            cell: (row) => (
                <span className="text-muted-foreground" title={formatInstant(row.latest.created_at)}>
                    {formatRelative(row.latest.created_at)}
                </span>
            ),
        },
        {
            id: 'median',
            header: LABELS.runs.grouped.median,
            className: 'text-right font-mono text-xs',
            cell: (row) =>
                row.median_duration_ms === null ? null : (
                    <span>{formatDuration(row.median_duration_ms)}</span>
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
