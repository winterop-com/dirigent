import { Chart } from '@winterop-com/sokkel-ui-charts/Chart'
import { Section } from '@winterop-com/sokkel-ui/Section'
import { useMemo } from 'react'
import { chartSummary, stackOf, tallest, type HourBucket } from '@/lib/home'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/** How often the foot of the chart names an hour. Every sixth, so the day reads 00, 06, 12, 18. */
const LABEL_EVERY = 6

/** Which of an hour's counts a band draws. */
type Band = 'succeeded' | 'withErrors' | 'failed'

/**
 * The three outcomes a bar is stacked out of, worst at the top: the chart's color token for each,
 * and the same color as a class for the legend's swatch.
 */
const BANDS: readonly { id: Band; label: string; color: string; swatch: string }[] = [
    {
        id: 'failed',
        label: LABELS.state.run.failed.tile,
        color: 'status-failed/80',
        swatch: 'bg-status-failed/80',
    },
    {
        id: 'withErrors',
        label: LABELS.state.run.completed_with_errors.tile,
        color: 'status-completed-with-errors/80',
        swatch: 'bg-status-completed-with-errors/80',
    },
    {
        id: 'succeeded',
        label: LABELS.state.run.succeeded.tile,
        color: 'muted-foreground/45',
        swatch: 'bg-muted-foreground/45',
    },
]

const COLORS = Object.fromEntries(BANDS.map((band) => [band.label, band.color]))

/** The stack from the bottom up: succeeded first, failed on top. */
const STACK_ORDER = BANDS.map((band) => band.label).toReversed()

const hourLabel = (bucket: HourBucket) => `${String(bucket.hour).padStart(2, '0')}:00`

/**
 * One row per outcome an hour has, and a single zero for an hour with none, which the chart draws
 * as its one-pixel baseline.
 */
function chartRows(buckets: readonly HourBucket[]) {
    return buckets.flatMap((bucket) => {
        const hour = hourLabel(bucket)
        if (stackOf(bucket) === 0) return [{ hour, outcome: LABELS.state.run.succeeded.tile, runs: 0 }]
        return BANDS.filter((band) => bucket[band.id] > 0).map((band) => ({
            hour,
            outcome: band.label,
            runs: bucket[band.id],
        }))
    })
}

/**
 * The last day of runs, one bar an hour, stacked by how each hour came out, on a quiet axis: no
 * gridlines and no scale, the hour under every sixth bar. An hour's counts are on its tooltip, and
 * the whole of the chart is its accessible name.
 */
export function RunsChart({
    buckets,
    reading,
    className,
}: {
    buckets: readonly HourBucket[]
    /** Whether the read behind it has yet to land, which is a bar row of nothing at all. */
    reading: boolean
    className?: string
}) {
    const rows = useMemo(() => chartRows(buckets), [buckets])
    if (!reading && tallest(buckets) === 0) {
        return (
            <Section
                title={LABELS.dashboard.chart.title}
                meta={LABELS.dashboard.chart.window}
                className={className}
            >
                <p className="text-sm text-muted-foreground">{LABELS.dashboard.chart.summary_empty}</p>
            </Section>
        )
    }
    return (
        <Section
            title={LABELS.dashboard.chart.title}
            meta={reading ? LABELS.shell.reading : LABELS.dashboard.chart.window}
            className={className}
            bodyClassName="flex flex-col gap-3"
        >
            <Chart
                kind="bar"
                label={chartSummary(buckets)}
                rows={rows}
                x="hour"
                y="runs"
                series="outcome"
                stack="stacked"
                seriesOrder={STACK_ORDER}
                colors={COLORS}
                labelEvery={LABEL_EVERY}
                quiet
                baseline
                className="h-40"
            />

            <ul className="flex flex-wrap items-center gap-x-4 gap-y-1">
                {BANDS.map((band) => (
                    <li key={band.id} className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <span className={cn('size-2 shrink-0 rounded-sm', band.swatch)} aria-hidden />
                        {band.label}
                    </li>
                ))}
            </ul>
        </Section>
    )
}
