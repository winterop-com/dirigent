import { Link } from 'react-router'

import { Instant } from '@/components/Instant'
import { Copyable, Fact, Section } from '@/components/run/Panel'
import { StatusChip } from '@/components/run/StatusChip'
import { asJson, elapsedBetween, formatDuration, formatWindow } from '@/lib/format'
import type { RunOut } from '@/lib/runs'

export const COPY_TRACE_LABEL = 'Copy the trace id'
export const COPY_RUN_LABEL = 'Copy the run id'

/**
 * The run itself: what it was given, who asked for it, when it happened, and what it is on.
 *
 * The parameters are drawn as they were validated -- a JSON value per name -- rather than as a
 * flattened string: a parameter may be an object or a list, and a run reproduced from what this
 * pane shows has to carry the same value.
 *
 * A WINDOW IS A ROW OR IT IS NOTHING, AND SO IS A TRACE. Most runs carry no logical data
 * interval, and an instance with no OpenTelemetry behind it traces none of its runs; a row
 * reading "not windowed" or "not traced" on every one of them would be a column of nothing. Each
 * row appears only where there is something to read in it.
 *
 * AND IT IS THE ONE INSTANT HERE READ EXACTLY. Created, started and finished are read by how
 * recent they are; a window is what a step filtered its query on, so it reads as the two
 * instants themselves, with the pair as the wire wrote them on hover.
 */
export function RunTab({ run }: { run: RunOut }) {
    const params = Object.entries(run.params)
    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="flex items-center gap-2">
                <StatusChip status={run.status} />
                <span className="text-xs text-muted-foreground">
                    {formatDuration(elapsedBetween(run.started_at, run.finished_at))}
                </span>
            </div>

            {run.error !== null && <p className="text-xs break-words text-critical">{run.error}</p>}

            <Section title="Trigger">
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <Fact term="kind" detail={run.triggered_by_kind} />
                    <Fact term="by" detail={run.triggered_by_label ?? 'not recorded'} />
                </dl>
            </Section>

            <Section title="Timing">
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <Fact term="created" detail={<Instant at={run.created_at} />} />
                    <Fact term="started" detail={<Instant at={run.started_at} />} />
                    <Fact term="finished" detail={<Instant at={run.finished_at} />} />
                    {run.window_start !== null && run.window_end !== null && (
                        <Fact
                            term="window"
                            detail={
                                <span title={`${run.window_start} to ${run.window_end}`}>
                                    {formatWindow(run.window_start, run.window_end)}
                                </span>
                            }
                        />
                    )}
                </dl>
            </Section>

            <Section title="Parameters">
                {params.length === 0 ? (
                    <p className="text-xs text-muted-foreground">This run was started with no parameters.</p>
                ) : (
                    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                        {params.map(([name, value]) => (
                            <Fact
                                key={name}
                                term={name}
                                detail={<span className="font-mono">{asJson(value)}</span>}
                            />
                        ))}
                    </dl>
                )}
            </Section>

            <Section title="Definition">
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <Fact
                        term="pipeline"
                        detail={
                            <Link className="text-primary hover:underline" to={`/pipelines/${run.pipeline}`}>
                                {run.pipeline}
                            </Link>
                        }
                    />
                    <Fact term="version" detail={run.pipeline_version} />
                    <Fact term="run" detail={<Copyable value={run.id} label={COPY_RUN_LABEL} />} />
                    {run.trace_id !== null && (
                        <Fact
                            term="trace"
                            detail={<Copyable value={run.trace_id} label={COPY_TRACE_LABEL} />}
                        />
                    )}
                </dl>
            </Section>
        </div>
    )
}
