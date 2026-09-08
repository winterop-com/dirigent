import { Fact, Section } from '@/components/run/Panel'
import { StatusChip } from '@/components/run/StatusChip'
import { countedHeading, formatBytes, formatDuration, shortenUri } from '@/lib/format'
import type { RunDetailState } from '@/lib/run-detail'
import type { Problem } from '@/lib/api'
import { itemsNote, type AttemptEvent, type RunReport } from '@/lib/runs'

/**
 * What the run produced: the artifacts its steps wrote, and the summary the API renders.
 *
 * AN ARTIFACT IS AN ATTEMPT'S OUTPUT THAT WENT TO STORAGE. An output small enough to inline is
 * on the attempt itself and is read on the step's own tab; what is listed here is the outputs
 * that became objects, which are the ones with a URI and a size.
 *
 * The report is read once when the run settles rather than followed: it is a summary of a
 * finished thing, and the event stream already says everything that is still moving.
 */
export function OutputTab({
    state,
    report,
    problem,
}: {
    state: RunDetailState
    report: RunReport | null
    problem: Problem | null
}) {
    const artifacts = state.order
        .map((id) => state.attempts[id])
        .filter((attempt): attempt is AttemptEvent => attempt !== undefined && attempt.output_uri !== null)
    const items = report === null ? null : itemsNote(report.items_total, report.items_failed)

    return (
        <div className="flex flex-col gap-4 p-4">
            <Section title={countedHeading('Artifacts', artifacts.length)}>
                {artifacts.length === 0 ? (
                    <p className="text-muted-foreground text-xs">No step of this run wrote its output to storage.</p>
                ) : (
                    <ul className="space-y-2">
                        {artifacts.map((attempt) => (
                            <li key={attempt.id} className="space-y-0.5">
                                <div className="flex items-baseline gap-2">
                                    <span className="truncate text-sm">{attempt.step_name}</span>
                                    {attempt.item !== null && (
                                        <span className="text-faint font-mono text-xs">{attempt.item}</span>
                                    )}
                                    <span className="text-muted-foreground ml-auto shrink-0 text-xs">
                                        {formatBytes(attempt.output_bytes)}
                                    </span>
                                </div>
                                <p className="identifier" title={attempt.output_uri ?? undefined}>
                                    {shortenUri(attempt.output_uri ?? '')}
                                </p>
                            </li>
                        ))}
                    </ul>
                )}
            </Section>

            <Section title="Report">
                {problem !== null ? (
                    <p className="text-muted-foreground text-xs">{problem.detail}</p>
                ) : report === null ? (
                    <p className="text-muted-foreground text-xs">Reading the summary.</p>
                ) : (
                    <>
                        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                            <Fact term="took" detail={formatDuration(report.duration_ms)} />
                            {items !== null && <Fact term="items" detail={items} />}
                        </dl>
                        <ul className="mt-2 space-y-1">
                            {report.steps.map((step) => (
                                <li key={step.step} className="flex items-center gap-2">
                                    <StatusChip status={step.outcome} />
                                    <span className="truncate text-sm">{step.step}</span>
                                    {step.warnings > 0 && (
                                        <span className="text-warning text-xs">{step.warnings} warned</span>
                                    )}
                                    <span className="text-faint ml-auto shrink-0 text-xs">
                                        {formatDuration(step.duration_ms)}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    </>
                )}
            </Section>
        </div>
    )
}
