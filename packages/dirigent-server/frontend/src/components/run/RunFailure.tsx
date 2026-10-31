import { useMemo } from 'react'
import { Link } from 'react-router'

import { HealthSaid } from '@/components/connections/Health'
import { Code } from '@/components/ds/Code'
import { Panel } from '@/components/ds/Panel'
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
    step,
    block,
    error,
    code,
    connection,
}: {
    run: RunOut
    /** The step the run failed in, where one did. */
    step: string | null
    block: string | null
    /** The sentence the step failed with, or the run's own where no attempt said one. */
    error: string | null
    code: string | null
    connection: ConnectionOut | null
}) {
    const params = Object.entries(run.params)
    return (
        <Panel
            tone="critical"
            title={step === null ? run.status : LABELS.runs.failure.heading(step)}
            meta={code ?? undefined}
            className="flex-[1_1_340px]"
        >
            {block !== null && <Code value={block} />}
            {error !== null && <p className="mt-3 text-base break-words">{error}</p>}
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
        </Panel>
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
        <Panel
            title={LABELS.runs.failure.logs}
            meta={String(lines.length)}
            inset={false}
            className="flex-[1.6_1_440px]"
            aside={
                step === null ? undefined : (
                    <span className="flex items-center gap-2 text-xs font-normal text-muted-foreground">
                        {LABELS.runs.failure.step_shown}
                        <Code value={step} tone="body" />
                        <Button variant="ghost" size="sm" onClick={onAllSteps}>
                            {LABELS.runs.failure.all_steps}
                        </Button>
                    </span>
                )
            }
        >
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
                            <span className={cn(failing(entry) && 'text-critical-ink')}>{entry.level}</span>
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
        </Panel>
    )
}
