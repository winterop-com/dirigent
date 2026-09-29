import type { CSSProperties, ReactNode } from 'react'
import { Link } from 'react-router'

import { Instant } from '@/components/Instant'
import { shortId } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import {
    clockOf,
    nextFireView,
    oneTimeView,
    watchView,
    type OutcomeTone,
    type ScheduleOut,
    type WatchOut,
} from '@/lib/triggers'

/**
 * The small things the triggers screen and its panel both draw of a trigger.
 *
 * The dot is filled from the semantic aliases in index.css -- what is good, what wants
 * attention, what failed -- because a firing is not a run and has no `--status-` token of its
 * own. Nothing here decides a colour; it names one.
 *
 * A SCHEDULE SAYS THE SAME THING IN A CELL AND IN A FACT. What its clock is and when it fires
 * next are two questions with one answer each, so the listing and the panel ask them here
 * rather than each spelling an instant its own way.
 */
const TONES: Record<OutcomeTone, string> = {
    good: 'var(--good)',
    warn: 'var(--warning)',
    critical: 'var(--critical)',
    quiet: 'var(--faint)',
}

/** One outcome's colour, with no room for its name. */
export function Dot({ tone }: { tone: OutcomeTone }) {
    return <span className="status-dot" style={{ '--chip': TONES[tone] } as CSSProperties} aria-hidden />
}

/** A word a trigger wears: where it came from, and whether it is running. */
export function Chip({ children }: { children: ReactNode }) {
    return (
        <span className="rounded-sm border border-border px-1.5 text-xs text-muted-foreground">
            {children}
        </span>
    )
}

/**
 * Who declared a trigger: the code of the triggers document that owns it, or that the
 * pipeline's own document does. The code is the fact where there is one; "managed" is the
 * fact only when the owner is the pipeline itself. A hand-made row wears neither.
 */
export function OwnerChip({ managed, document }: { managed: boolean; document: string | null }) {
    if (document !== null) {
        return (
            <Chip>
                <span className="font-mono">{document}</span>
            </Chip>
        )
    }
    return managed ? <Chip>{LABELS.triggers.managed}</Chip> : null
}

/** The one clock a schedule fires on, with a one-time moment read like any other instant. */
export function Clock({ schedule }: { schedule: ScheduleOut }) {
    const clock = clockOf(schedule)
    const once = clock.kind === 'at' ? oneTimeView(schedule) : null
    if (once !== null) {
        return (
            <span className="flex flex-wrap items-baseline gap-1.5 text-sm">
                {once.fired && (
                    <span className="text-xs text-muted-foreground">{LABELS.triggers.schedule.fired}</span>
                )}
                <Instant at={once.at} />
            </span>
        )
    }
    return <span className={clock.mono ? 'font-mono text-xs' : 'text-sm'}>{clock.text}</span>
}

/** When a schedule fires next, or that nothing is scheduled; a paused one draws nothing, its chip says it. */
export function NextFire({ schedule }: { schedule: ScheduleOut }) {
    const next = nextFireView(schedule)
    return (
        <span data-testid="next-fire">
            {next.kind === 'none' && (
                <span className="text-faint">{LABELS.triggers.schedule.nothing_scheduled}</span>
            )}
            {next.kind === 'due' && <Instant className="text-muted-foreground" at={next.at} />}
        </span>
    )
}

/** What a watch is doing: the run it has waiting, or why it has none; a paused one wears its chip instead. */
export function WatchState({ watch }: { watch: WatchOut }) {
    const view = watchView(watch)
    return (
        <span className="flex items-center gap-2 text-xs">
            <Dot tone={view.tone} />
            {view.kind === 'waiting' && (
                <Link
                    className="font-mono text-primary-ink hover:underline"
                    to={`/runs/${view.runId}`}
                    onClick={(event) => {
                        event.stopPropagation()
                    }}
                >
                    {shortId(view.runId)}
                </Link>
            )}
            {view.kind === 'backing-off' && (
                <span className="flex items-baseline gap-1.5 text-muted-foreground">
                    {LABELS.triggers.watch.backing_off_until} <Instant at={view.until} />
                </span>
            )}
            {view.kind === 'arming' && <span className="text-faint">{LABELS.triggers.watch.arming}</span>}
        </span>
    )
}
