import { instantFact } from '@/components/Instant'
import { Copyable, PanelGroup } from '@/components/run/Panel'
import { DescriptionList } from '@winterop-com/sokkel-ui/DescriptionList'
import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { asJson, elapsedBetween, formatDuration, formatWindow } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import { startedAs, startedBy, type AttemptOut, type RunOut } from '@/lib/runs'
import { TextLink } from '@winterop-com/sokkel-ui/TextLink'

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

            <PanelGroup title={LABELS.word.trigger.label}>
                <p className="text-xs">
                    {started.from === null ? (
                        startedBy(run, attempts)
                    ) : (
                        <TextLink
                            variant="inline"
                            href={`/runs/${started.from}`}
                            title={started.recorded ?? undefined}
                        >
                            {started.said}
                        </TextLink>
                    )}
                </p>
            </PanelGroup>

            <PanelGroup title={LABELS.runs.timing}>
                <DescriptionList
                    items={[
                        { term: LABELS.word.created.term, value: instantFact(run.created_at) },
                        { term: LABELS.word.started.term, value: instantFact(run.started_at) },
                        { term: LABELS.runs.fact.finished, value: instantFact(run.finished_at) },
                        ...(run.window_start !== null && run.window_end !== null
                            ? [
                                  {
                                      term: LABELS.word.window.term,
                                      value: (
                                          <span
                                              title={LABELS.measure.range(run.window_start, run.window_end)}
                                          >
                                              {formatWindow(run.window_start, run.window_end)}
                                          </span>
                                      ),
                                  },
                              ]
                            : []),
                    ]}
                />
            </PanelGroup>

            <PanelGroup title={LABELS.word.parameters}>
                {params.length === 0 ? (
                    <p className="text-xs text-muted-foreground">{LABELS.runs.no_parameters}</p>
                ) : (
                    <DescriptionList
                        items={params.map(([name, value]) => ({
                            term: <InlineCode value={name} tone="muted" bare size="xs" />,
                            value: asJson(value),
                            code: true,
                        }))}
                    />
                )}
            </PanelGroup>

            <PanelGroup title={LABELS.word.definition}>
                <DescriptionList
                    items={[
                        {
                            term: LABELS.word.pipeline.term,
                            value: (
                                <TextLink variant="data" code href={`/pipelines/${run.pipeline}`}>
                                    {run.pipeline}
                                </TextLink>
                            ),
                        },
                        { term: LABELS.word.version.term, value: run.pipeline_version, numeric: true },
                        {
                            term: LABELS.word.run.term,
                            value: <Copyable value={run.id} label={COPY_RUN_LABEL} />,
                        },
                        ...(run.trace_id === null
                            ? []
                            : [
                                  {
                                      term: LABELS.runs.fact.trace,
                                      value: <Copyable value={run.trace_id} label={COPY_TRACE_LABEL} />,
                                  },
                              ]),
                    ]}
                />
            </PanelGroup>
        </div>
    )
}
