import { Link } from 'react-router'

import { HealthSaid } from '@/components/connections/Health'
import { Code } from '@/components/ds/Code'
import { Panel } from '@/components/ds/Panel'
import type { Issue, JsonMap } from '@/lib/api'
import { healthOf, type ConnectionOut } from '@/lib/connections'
import { LABELS } from '@/lib/labels'
import { issueSentence } from '@/lib/refusal'
import type { RunOut } from '@/lib/runs'
import { statusLabel } from '@/lib/status'

/** A failure that lists no problems of its own. */
const NO_PROBLEMS: readonly Issue[] = []

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
 *
 * A REFUSED CONFIG IS ITS PROBLEMS. Where the failure lists them, each is drawn as the field it is
 * at and what is wrong there, and the sentence -- which is the first of them -- is not drawn too.
 */
export function RunFailure({
    run,
    step,
    items = false,
    block,
    error,
    code,
    problems = NO_PROBLEMS,
    connection,
}: {
    run: RunOut
    /** The step the run failed in, where one did. */
    step: string | null
    /** The step carried on, and what failed was some of its items. */
    items?: boolean
    block: string | null
    /** The sentence the step failed with, or the run's own where no attempt said one. */
    error: string | null
    code: string | null
    /** The problems the failure lists one by one, where it lists any. */
    problems?: readonly Issue[]
    connection: ConnectionOut | null
}) {
    const params = Object.entries(run.params)
    return (
        <Panel
            tone="critical"
            title={
                step === null
                    ? statusLabel(run.status)
                    : items
                      ? LABELS.runs.failure.items_heading(step)
                      : LABELS.runs.failure.heading(step)
            }
            meta={code ?? undefined}
        >
            {block !== null && <Code value={block} />}
            {problems.length > 0 ? (
                <ul className="mt-3 space-y-1.5" aria-label={LABELS.runs.failure.problems}>
                    {problems.map((problem, index) => (
                        <li
                            key={`${problem.location ?? ''}:${String(index)}`}
                            className="flex min-w-0 items-baseline gap-2.5"
                        >
                            {problem.location !== null && <Code value={problem.location} tone="body" />}
                            <span className="min-w-0 text-base break-words">{issueSentence(problem)}</span>
                        </li>
                    ))}
                </ul>
            ) : (
                error !== null && <p className="mt-3 text-base break-words">{error}</p>
            )}
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
