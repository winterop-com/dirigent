import { useMemo } from 'react'
import { Link } from 'react-router'

import { Section } from '@winterop-com/sokkel-ui/Section'
import { Segmented } from '@winterop-com/sokkel-ui/Segmented'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { UptimeBar, type UptimeDay } from '@winterop-com/sokkel-ui/UptimeBar'
import { formatDuration, formatRelative } from '@/lib/format'
import { ELEMENT_DAYS, elementDays, stepsOf, type ItemHealth, type ItemStats } from '@/lib/item-stats'
import { LABELS } from '@/lib/labels'

const WORDS = LABELS.pipelines.page.elements

/**
 * Each fan-out element's record over the last days, one step at a time: a monitor's targets.
 *
 * ONE STEP'S ELEMENTS AT A TIME. Every check of a monitor maps over the same targets, so drawing
 * them all is the grid of targets by checks again. The step is the one chosen in the graph when
 * it fans out, else the first, which is where a grid is usually drawn from; the control above
 * chooses another, and choosing one here chooses it in the graph too.
 *
 * Drawn only once a settled run has carried an element: a pipeline with no fan-out, or none run
 * yet, has nothing for this panel to say.
 */
export function ElementHealth({
    stats,
    selected,
    onSelect,
    className,
}: {
    stats: ItemStats
    /** The step chosen in the graph, if any. */
    selected: string | null
    onSelect: (step: string) => void
    className?: string
}) {
    const steps = useMemo(() => stepsOf(stats), [stats])
    const step = selected !== null && steps.includes(selected) ? selected : steps[0]
    const today = useMemo(() => new Date(stats.window.end), [stats.window.end])
    const rows = stats.items.filter((row) => row.step === step)
    return (
        <Section
            title={WORDS.title}
            flush
            className={className}
            actions={
                steps.length > 1 ? (
                    <Segmented
                        label={WORDS.step}
                        size="sm"
                        value={step}
                        options={steps.map((one) => ({ value: one, label: one }))}
                        onValueChange={onSelect}
                    />
                ) : undefined
            }
        >
            <div data-testid="pipeline-elements">
                {rows.map((row) => (
                    <ElementRow key={`${row.step}\u0000${row.item}`} row={row} today={today} />
                ))}
            </div>
        </Section>
    )
}

/** One element: how it stands now, its key, how slow it runs, and its days as an uptime bar. */
function ElementRow({ row, today }: { row: ItemHealth; today: Date }) {
    const days: UptimeDay[] = elementDays(row, today).map((one) => ({
        date: one.date,
        uptime: one.uptime,
        note: one.failed > 0 ? WORDS.failed_of(one.failed, one.ran) : undefined,
    }))
    return (
        <div className="flex min-w-0 flex-col gap-2 border-t border-border px-4 py-3 first:border-t-0">
            <div className="flex min-w-0 items-center gap-3">
                <Link to={`/runs/${row.last_run_id}`} className="shrink-0">
                    <StatusChip status={row.last_status} />
                </Link>
                <span className="min-w-0 flex-1 truncate font-mono text-xs" title={row.item}>
                    {row.item}
                </span>
                {row.last_failed_at !== null && (
                    <span
                        className="hidden shrink-0 text-xs text-muted-foreground sm:inline"
                        title={row.last_error ?? undefined}
                    >
                        {WORDS.last_failed(formatRelative(row.last_failed_at))}
                    </span>
                )}
                {row.p95_duration_ms !== null && (
                    <span className="shrink-0 font-mono text-xs text-muted-foreground">
                        {WORDS.p95(formatDuration(row.p95_duration_ms))}
                    </span>
                )}
            </div>
            <UptimeBar
                days={days}
                label={WORDS.bar(row.item, row.step, ELEMENT_DAYS)}
                words={{
                    uptime: WORDS.uptime,
                    since: WORDS.since,
                    today: WORDS.today,
                    noData: WORDS.no_runs,
                }}
            />
        </div>
    )
}
