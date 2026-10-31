import { useMemo } from 'react'
import { Link } from 'react-router'

import { HealthSaid } from '@/components/connections/Health'
import { Code } from '@/components/ds/Code'
import { SectionHeading } from '@/components/ds/SectionHeading'
import { Surface } from '@/components/ds/Surface'
import { Button } from '@/components/ui/button'
import type { JsonMap } from '@/lib/api'
import { healthOf, type ConnectionOut } from '@/lib/connections'
import { formatClock, formatInstant } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import type { LogEntryOut, RunOut } from '@/lib/runs'
import { cn } from '@/lib/utils'

/** How many lines the log beside the failure draws; the terminal holds the rest. */
const LOG_LINES = 200

/** A value as one line of text, the way a fact or a log field is drawn. */
function said(value: unknown): string {
    return typeof value === 'string' ? value : JSON.stringify(value)
}

/** The connection a step's config names, which is what a failure most often turns out to be about. */
export function connectionOf(config: JsonMap | null): string | null {
    const named = config?.connection
    return typeof named === 'string' && !named.includes('${') ? named : null
}

/**
 * What a run failed with: the step, its block, the catalogued code, the sentence, the connection
 * the step named and how that one is, and the parameters the run was given.
 */
export function RunFailure({
    run,
    block,
    connection,
}: {
    run: RunOut
    block: string | null
    connection: ConnectionOut | null
}) {
    const step = run.failed_step
    const params = Object.entries(run.params)
    return (
        <Surface
            tone="critical"
            className="flex min-w-0 flex-[1_1_340px] flex-col p-5"
            aria-label={step ?? undefined}
        >
            <div className="flex flex-wrap items-baseline justify-between gap-x-3.5 gap-y-1.5">
                <h2 className="min-w-0 truncate text-title font-semibold text-critical-ink">
                    {step === null ? run.status : LABELS.runs.failure.heading(step)}
                </h2>
                {run.error_code !== null && <Code value={run.error_code} />}
            </div>
            {block !== null && (
                <div className="mt-1">
                    <Code value={block} />
                </div>
            )}
            {run.error !== null && <p className="mt-3 text-base break-words">{run.error}</p>}
            {connection !== null && (
                <Link
                    to={`/connections/${encodeURIComponent(connection.code)}`}
                    className="-mx-2 mt-4 flex items-center gap-2.5 rounded-md p-2 text-sm hover:bg-background/40"
                >
                    <span className="min-w-0 flex-1 truncate">
                        {connection.name !== null && <span className="font-medium">{connection.name} </span>}
                        <Code value={connection.code} />
                    </span>
                    <HealthSaid view={healthOf(connection)} />
                </Link>
            )}
            {params.length > 0 && (
                <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-5 gap-y-1.5 border-t border-critical/20 pt-3.5 text-xs">
                    {params.map(([key, value]) => (
                        <div key={key} className="contents">
                            <dt className="text-muted-foreground">{key}</dt>
                            <dd className="min-w-0">
                                <Code value={said(value)} tone="body" />
                            </dd>
                        </div>
                    ))}
                </dl>
            )}
        </Surface>
    )
}

/** Whether a line is one a reader of a failure is looking for. */
function failing(entry: LogEntryOut): boolean {
    return entry.level === 'error'
}

/**
 * The run's log lines, latest first, the failing ones on the failure's wash with the fields they
 * carried under them. Choosing a step narrows it to that step.
 */
export function RunLogs({
    logs,
    step,
    onAllSteps,
    onStep,
}: {
    logs: readonly LogEntryOut[]
    step: string | null
    onAllSteps: () => void
    onStep: (step: string) => void
}) {
    const lines = useMemo(
        () =>
            logs
                .filter((entry) => step === null || entry.step_name === step)
                .slice(-LOG_LINES)
                .toReversed(),
        [logs, step],
    )
    return (
        <section className="flex min-w-0 flex-[1.6_1_440px] flex-col" aria-labelledby="run-logs">
            <div className="mb-1.5 flex min-h-9 items-center justify-between gap-3">
                <SectionHeading id="run-logs">{LABELS.runs.failure.logs}</SectionHeading>
                {step !== null && (
                    <span className="flex items-center gap-2 text-xs text-muted-foreground">
                        {LABELS.runs.failure.step_shown}
                        <Code value={step} tone="body" />
                        <Button variant="ghost" size="sm" onClick={onAllSteps}>
                            {LABELS.runs.failure.all_steps}
                        </Button>
                    </span>
                )}
            </div>
            <Surface inset={false} as="div">
                {lines.length === 0 ? (
                    <p className="p-4 text-sm text-muted-foreground">{LABELS.runs.failure.no_logs}</p>
                ) : (
                    lines.map((entry) => (
                        <div
                            key={entry.id}
                            className={cn(
                                'border-t border-border px-4 py-3 first:border-t-0',
                                failing(entry) && 'bg-critical-wash',
                            )}
                        >
                            <div className="flex flex-wrap items-center gap-x-3.5 gap-y-1 font-mono text-xs text-muted-foreground">
                                <time title={formatInstant(entry.created_at)}>
                                    {formatClock(entry.created_at)}
                                </time>
                                <span className={cn(failing(entry) && 'text-critical-ink')}>
                                    {entry.level}
                                </span>
                                {entry.step_name !== null && (
                                    <button
                                        type="button"
                                        className="rounded-sm text-foreground outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                                        onClick={() => {
                                            if (entry.step_name !== null) onStep(entry.step_name)
                                        }}
                                    >
                                        {entry.step_name}
                                    </button>
                                )}
                            </div>
                            <p className="mt-1.5 font-mono text-xs break-words">{entry.message}</p>
                            {entry.fields !== null && Object.keys(entry.fields).length > 0 && (
                                <div className="mt-1 font-mono text-xs break-all">
                                    {Object.entries(entry.fields).map(([key, value]) => (
                                        <div key={key}>
                                            <span className="text-muted-foreground">{key}</span> {said(value)}
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    ))
                )}
            </Surface>
        </section>
    )
}
