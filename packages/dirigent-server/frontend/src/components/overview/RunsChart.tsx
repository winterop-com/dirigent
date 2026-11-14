import { Chart } from '@winterop-com/sokkel-ui-charts/Chart'
import { chartLegend } from '@winterop-com/sokkel-ui-charts/chart-legend'
import { ChartLegend } from '@winterop-com/sokkel-ui-charts/ChartLegend'
import type { ChartSpec } from '@winterop-com/sokkel-ui-charts/kinds'
import { Section } from '@winterop-com/sokkel-ui/Section'
import { useMemo, useState } from 'react'
import { chartSummary, stackOf, tallest, type HourBucket } from '@/lib/home'
import { LABELS } from '@/lib/labels'

/** How often the foot of the chart names an hour. Every sixth, so the day reads 00, 06, 12, 18. */
const LABEL_EVERY = 6

/** Which of an hour's counts a band draws. */
type Band = 'succeeded' | 'withErrors' | 'failed'

/** The three outcomes a bar is stacked out of, worst at the top, and the chart's color token for each. */
const BANDS: readonly { id: Band; label: string; color: string }[] = [
    { id: 'failed', label: LABELS.state.run.failed.tile, color: 'status-failed/80' },
    {
        id: 'withErrors',
        label: LABELS.state.run.completed_with_errors.tile,
        color: 'status-completed-with-errors/80',
    },
    { id: 'succeeded', label: LABELS.state.run.succeeded.tile, color: 'muted-foreground/45' },
]

const COLORS = Object.fromEntries(BANDS.map((band) => [band.label, band.color]))

/** The outcomes worst first, as the legend lists them. */
const WORST_FIRST = BANDS.map((band) => band.label)

/** The stack from the bottom up: succeeded first, failed on top. */
const STACK_ORDER = WORST_FIRST.toReversed()

/** The hour a bar stands for, as the clock's two digits: what the rows key it by. */
const hourOf = (bucket: HourBucket) => String(bucket.hour).padStart(2, '0')

/** The hour as the axis and the tooltip write it: on the hour. */
const onTheHour = (hour: string) => `${hour}:00`

/**
 * Three rows an hour, one per outcome, keyed by the hour's two digits. An outcome the hour
 * did not have is missing rather than zero, so it draws nothing and its tooltip leaves it out, and
 * an hour with no settled run has a zero for the chart's one-pixel baseline.
 */
function chartRows(buckets: readonly HourBucket[]) {
    return buckets.flatMap((bucket) => {
        const hour = hourOf(bucket)
        const empty = stackOf(bucket) === 0
        return BANDS.map((band) => ({
            hour,
            outcome: band.label,
            runs: bucket[band.id] > 0 ? bucket[band.id] : empty && band.id === 'succeeded' ? 0 : null,
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
    const spec = useMemo<ChartSpec>(
        () => ({
            rows: chartRows(buckets),
            x: 'hour',
            y: 'runs',
            series: 'outcome',
            stack: 'stacked',
            seriesOrder: STACK_ORDER,
            colors: COLORS,
            labelEvery: LABEL_EVERY,
            formatCategory: onTheHour,
            quiet: true,
            baseline: true,
        }),
        [buckets],
    )
    // Worst first, as the bars are read from the top; each band keeps its color by name.
    const legend = useMemo(() => chartLegend('bar', { ...spec, seriesOrder: WORST_FIRST }), [spec])
    const [hidden, setHidden] = useState<ReadonlySet<string>>(() => new Set())
    const [hovered, setHovered] = useState<string | null>(null)
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
                {...spec}
                hidden={hidden}
                hovered={hovered}
                className="h-40"
            />
            <ChartLegend
                items={legend}
                hidden={hidden}
                onToggle={(key) => {
                    setHidden((now) => {
                        const next = new Set(now)
                        if (!next.delete(key)) next.add(key)
                        return next
                    })
                }}
                onHover={setHovered}
                className="-mx-1.5"
            />
        </Section>
    )
}
