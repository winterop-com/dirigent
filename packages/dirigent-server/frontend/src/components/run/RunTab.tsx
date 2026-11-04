import { Link } from 'react-router'

import { Instant } from '@/components/Instant'
import { Copyable, Fact, Section } from '@/components/run/Panel'
import { StatusChip } from '@/components/run/StatusChip'
import { asJson, elapsedBetween, formatDuration, formatWindow } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import { startedAs, startedBy, type AttemptOut, type RunOut } from '@/lib/runs'

export const COPY_TRACE_LABEL = LABELS.runs.copy_trace
export const COPY_RUN_LABEL = LABELS.runs.copy_run_id

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
 * A FAILURE IS SAID ONCE. A run that failed or completed with errors has the screen's failure card
 * beside this pane, naming the step and what it said, so the pane carries only a reason the card
 * does not: a cancellation's.
 *
 * AND IT IS THE ONE INSTANT HERE READ EXACTLY. Created, started and finished are read by how
 * recent they are; a window is what a step filtered its query on, so it reads as the two
 * instants themselves, with the pair as the wire wrote them on hover.
 */
export function RunTab({ run, attempts }: { run: RunOut; attempts: readonly AttemptOut[] }) {
    const params = Object.entries(run.params)
    const started = startedAs(run)
    const troubled = run.status === 'failed' || run.status === 'completed_with_errors'
    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="flex items-center gap-2">
                <StatusChip status={run.status} />
                <span className="text-xs text-muted-foreground">
                    {formatDuration(elapsedBetween(run.started_at, run.finished_at))}
                </span>
            </div>

            {run.error !== null && !troubled && (
                <p className="text-xs break-words text-critical">{run.error}</p>
            )}

            <Section title={LABELS.word.trigger.label}>
                <p className="text-xs">
                    {started.from === null ? (
                        startedBy(run, attempts)
                    ) : (
                        <Link
                            className="text-foreground underline-offset-2 hover:underline"
                            to={`/runs/${started.from}`}
                            title={started.recorded ?? undefined}
                        >
                            {started.said}
                        </Link>
                    )}
                </p>
            </Section>

            <Section title={LABELS.runs.timing}>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <Fact term={LABELS.word.created.term} detail={<Instant at={run.created_at} />} />
                    <Fact term={LABELS.word.started.term} detail={<Instant at={run.started_at} />} />
                    <Fact term={LABELS.runs.fact.finished} detail={<Instant at={run.finished_at} />} />
                    {run.window_start !== null && run.window_end !== null && (
                        <Fact
                            term={LABELS.word.window.term}
                            detail={
                                <span title={LABELS.measure.range(run.window_start, run.window_end)}>
                                    {formatWindow(run.window_start, run.window_end)}
                                </span>
                            }
                        />
                    )}
                </dl>
            </Section>

            <Section title={LABELS.word.parameters}>
                {params.length === 0 ? (
                    <p className="text-xs text-muted-foreground">{LABELS.runs.no_parameters}</p>
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

            <Section title={LABELS.word.definition}>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <Fact
                        term={LABELS.word.pipeline.term}
                        detail={
                            <Link
                                className="text-foreground underline-offset-2 hover:underline"
                                to={`/pipelines/${run.pipeline}`}
                            >
                                {run.pipeline}
                            </Link>
                        }
                    />
                    <Fact term={LABELS.word.version.term} detail={run.pipeline_version} />
                    <Fact
                        term={LABELS.word.run.term}
                        detail={<Copyable value={run.id} label={COPY_RUN_LABEL} />}
                    />
                    {run.trace_id !== null && (
                        <Fact
                            term={LABELS.runs.fact.trace}
                            detail={<Copyable value={run.trace_id} label={COPY_TRACE_LABEL} />}
                        />
                    )}
                </dl>
            </Section>
        </div>
    )
}
