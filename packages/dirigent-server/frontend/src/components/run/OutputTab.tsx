import { useEffect, useState } from 'react'

import { Section } from '@/components/run/Panel'
import { useApiPrefix } from '@/hooks/use-api-prefix'
import { artifactUrl, readArtifacts, reportArtifact, type ArtifactOut } from '@/lib/artifacts'
import { countedHeading, formatBytes, shortenUri } from '@/lib/format'
import type { RunDetailState } from '@/lib/run-detail'
import { runSettled } from '@/lib/status'

/**
 * What the run wrote down, each row a link to the content itself.
 *
 * AN ARTIFACT IS A ROW THE RUN HOLDS, NOT SOMETHING DERIVED FROM AN ATTEMPT.
 * `GET /runs/{id}/artifacts` is the listing, so an output that inlined is here beside one that
 * went to storage -- both are read back through `GET /artifacts/{id}`, and a link is what takes
 * a reader to one. A small output is still drawn as a value on the step's own tab, because a
 * value somebody can read is not a file they should have to download.
 *
 * THE REPORT DOCUMENT IS NOT HERE. It is the run's own account of itself rather than a step's
 * output, and the Report tab draws it.
 *
 * THE WIRE ROW NAMES THE STEP BUT NOT THE FAN-OUT ELEMENT, so an element's label is taken from
 * the attempt that wrote the same uri -- which the event stream has already reported.
 */
export function OutputTab({ state, runId }: { state: RunDetailState; runId: string }) {
    const [artifacts, setArtifacts] = useState<ArtifactOut[] | null>(null)
    const prefix = useApiPrefix()
    // A run writes its outputs as it goes and its report document as it settles, so the
    // listing is read again once nothing more can be added to it.
    const settled = runSettled(state.run.status)

    useEffect(() => {
        let cancelled = false
        void readArtifacts(runId).then(
            (rows) => {
                if (!cancelled) setArtifacts(rows)
            },
            () => {
                if (!cancelled) setArtifacts([])
            },
        )
        return () => {
            cancelled = true
        }
    }, [runId, settled])

    const report = artifacts === null ? null : reportArtifact(artifacts)
    const rows = artifacts === null ? [] : artifacts.filter((row) => row.id !== report?.id)
    const items = new Map<string, string>(
        state.order.flatMap((id) => {
            const attempt = state.attempts[id]
            if (attempt === undefined || attempt.output_uri === null || attempt.item === null) return []
            return [[attempt.output_uri, attempt.item] as [string, string]]
        }),
    )

    return (
        <div className="flex flex-col gap-4 p-4">
            <Section title={artifacts === null ? 'Artifacts' : countedHeading('Artifacts', rows.length)}>
                {artifacts === null ? (
                    <p className="text-xs text-muted-foreground">Reading the artifacts.</p>
                ) : rows.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No step of this run wrote an output.</p>
                ) : (
                    <ul className="space-y-2">
                        {rows.map((row) => (
                            <li key={row.id} className="space-y-0.5">
                                <div className="flex items-baseline gap-2">
                                    {prefix === null ? (
                                        <span className="truncate text-sm">{row.step_name ?? 'the run'}</span>
                                    ) : (
                                        <a
                                            className="truncate text-sm text-primary-ink hover:underline"
                                            href={artifactUrl(prefix, row.id)}
                                            download
                                            rel="noopener"
                                        >
                                            {row.step_name ?? 'the run'}
                                        </a>
                                    )}
                                    {row.uri !== null && items.get(row.uri) !== undefined && (
                                        <span className="font-mono text-xs text-faint">
                                            {items.get(row.uri)}
                                        </span>
                                    )}
                                    <span className="ml-auto shrink-0 text-xs text-muted-foreground">
                                        {formatBytes(row.size_bytes)}
                                    </span>
                                </div>
                                {/* A row with no uri inlined on the run, and has no location to state. */}
                                {row.uri !== null && (
                                    <p className="identifier" title={row.uri}>
                                        {shortenUri(row.uri)}
                                    </p>
                                )}
                            </li>
                        ))}
                    </ul>
                )}
            </Section>
        </div>
    )
}
