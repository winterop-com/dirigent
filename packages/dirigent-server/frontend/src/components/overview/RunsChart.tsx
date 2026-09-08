import { Card, CardContent } from '@/components/ui/card'
import { chartSummary, stackOf, tallest, type HourBucket } from '@/lib/home'
import { cn } from '@/lib/utils'

/** How often the foot of the chart names an hour. Every sixth, so the day reads 00, 06, 12, 18. */
const LABEL_EVERY = 6

/** Which of an hour's counts a band draws. */
type Band = 'succeeded' | 'withErrors' | 'failed'

/** The three outcomes a bar is stacked out of, worst at the top, and the token each is drawn in. */
const BANDS: readonly { id: Band; label: string; fill: string }[] = [
    { id: 'failed', label: 'Failed', fill: 'bg-status-failed/80' },
    { id: 'withErrors', label: 'With errors', fill: 'bg-status-completed-with-errors/80' },
    { id: 'succeeded', label: 'Succeeded', fill: 'bg-status-succeeded/75' },
]

/** One hour, said the way the panel's own legend says it. */
function bucketNote(bucket: HourBucket): string {
    const hour = `${String(bucket.hour).padStart(2, '0')}:00`
    if (bucket.total === 0) return `${hour} — nothing ran`
    const said = BANDS.filter((band) => bucket[band.id] > 0).map(
        (band) => `${String(bucket[band.id])} ${band.label.toLowerCase()}`,
    )
    const settled = said.length === 0 ? 'none finished' : said.join(', ')
    return `${hour} — ${String(bucket.total)} started, ${settled}`
}

/**
 * The last day of runs, one bar an hour, stacked by how each hour came out.
 *
 * PLAIN ELEMENTS, NOT A CHART LIBRARY. Twenty-four stacks of three is a row of divs whose
 * heights are a fraction, and every colour in it is a status token this app already owns -- a
 * charting library would arrive with a palette of its own and a megabyte to draw it in.
 *
 * THE AXIS IS QUIET. No gridlines and no scale: a bar chart of counts is read by comparing bars
 * to each other, and the hour under every sixth bar is what says which part of the day is which.
 * The whole of an hour is on the bar's title, and the whole of the chart is its accessible name.
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
    const most = tallest(buckets)
    return (
        <Card className={cn('gap-0 p-0', className)}>
            <CardContent className="space-y-3 p-3">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                    <div className="space-y-1">
                        <h2 className="text-sm font-semibold">Runs over time</h2>
                        <p className="text-muted-foreground text-xs">
                            {reading
                                ? 'Reading from the server'
                                : 'Every run started in the last 24 hours, by the hour it started in.'}
                        </p>
                    </div>
                    <ul className="flex items-center gap-3">
                        {BANDS.map((band) => (
                            <li key={band.id} className="text-muted-foreground flex items-center gap-1.5 text-xs">
                                <span className={cn('size-2 shrink-0 rounded-sm', band.fill)} aria-hidden />
                                {band.label}
                            </li>
                        ))}
                    </ul>
                </div>

                <div className="flex h-32 items-end gap-px" role="img" aria-label={chartSummary(buckets)}>
                    {buckets.map((bucket) => (
                        <div
                            key={bucket.start}
                            className="hover:bg-accent/40 flex h-full flex-1 flex-col justify-end rounded-sm"
                            title={bucketNote(bucket)}
                        >
                            {BANDS.map((band) =>
                                bucket[band.id] === 0 ? null : (
                                    <div
                                        key={band.id}
                                        className={cn('min-h-0.5 w-full', band.fill)}
                                        style={{ height: `${String((bucket[band.id] / Math.max(most, 1)) * 100)}%` }}
                                    />
                                ),
                            )}
                            {stackOf(bucket) === 0 && <div className="bg-border h-px w-full" />}
                        </div>
                    ))}
                </div>

                <div className="text-faint flex gap-px font-mono text-xs" aria-hidden>
                    {buckets.map((bucket, index) => (
                        <span key={bucket.start} className="flex-1 text-center">
                            {index % LABEL_EVERY === 0 ? `${String(bucket.hour).padStart(2, '0')}` : ''}
                        </span>
                    ))}
                </div>
            </CardContent>
        </Card>
    )
}
