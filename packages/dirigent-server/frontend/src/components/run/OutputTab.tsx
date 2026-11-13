import { useCallback, useEffect, useMemo, useState } from 'react'

import { DataTable, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { ProblemLine } from '@winterop-com/sokkel-ui/Problem'
import { FilePreview } from '@winterop-com/sokkel-ui/FilePreview'
import { useApiPrefix } from '@/hooks/use-api-prefix'
import type { Problem } from '@/lib/api'
import {
    artifactUrl,
    previewKindOf,
    previewLanguageOf,
    readArtifacts,
    readArtifactText,
    reportArtifact,
    type ArtifactOut,
    type PreviewKind,
} from '@/lib/artifacts'
import { FILE_PREVIEW_WORDS } from '@/lib/design-system'
import { formatBytes, shortenUri } from '@/lib/format'
import { PanelGroup } from '@/components/run/Panel'
import { LABELS } from '@/lib/labels'
import { refusalLine, refusalOf } from '@/lib/refusal'
import type { RunDetailState } from '@/lib/run-detail'
import { runSettled } from '@/lib/status'
import { TextLink } from '@winterop-com/sokkel-ui/TextLink'

const artifactId = (row: ArtifactOut) => row.id

/**
 * What the run wrote down, each row a link to the content itself.
 *
 * AN ARTIFACT IS A ROW THE RUN HOLDS, NOT SOMETHING DERIVED FROM AN ATTEMPT.
 * `GET /runs/{id}/artifacts` is the listing, so an output that inlined is here beside one that
 * went to storage -- both are read back through `GET /artifacts/{id}`, and a link is what takes
 * a reader to one. A small output is still drawn as a value on the step's own tab, because a
 * value somebody can read is not a file they should have to download.
 *
 * A ROW OF A KIND A PREVIEW CAN DRAW OPENS INTO ONE, read when it is opened and not before; a
 * row of another kind, or past the preview's size cap, is its link alone.
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
        // oxlint-disable-next-line react/exhaustive-effect-dependencies
    }, [runId, settled])

    const report = artifacts === null ? null : reportArtifact(artifacts)
    const rows = artifacts === null ? [] : artifacts.filter((row) => row.id !== report?.id)
    const items = useMemo(
        () =>
            new Map<string, string>(
                state.order.flatMap((id) => {
                    const attempt = state.attempts[id]
                    if (attempt === undefined || attempt.output_uri === null || attempt.item === null)
                        return []
                    return [[attempt.output_uri, attempt.item] as [string, string]]
                }),
            ),
        [state.attempts, state.order],
    )
    const columns = useMemo(() => artifactColumns(prefix, items), [prefix, items])
    const previewOf = useCallback(
        (row: ArtifactOut) => {
            const kind = previewKindOf(row)
            return kind === null ? null : (
                <ArtifactPreview row={row} kind={kind} name={artifactName(row, items)} />
            )
        },
        [items],
    )

    return (
        <div className="flex flex-col gap-4 p-4">
            <PanelGroup title={LABELS.word.artifacts} count={artifacts === null ? undefined : rows.length}>
                {artifacts === null ? (
                    <p className="text-xs text-muted-foreground">{LABELS.shell.reading}</p>
                ) : rows.length === 0 ? (
                    <p className="text-xs text-muted-foreground">{LABELS.runs.artifacts_empty}</p>
                ) : (
                    <DataTable
                        variant="list"
                        stackBelow={false}
                        resizable={false}
                        rowHeight="auto"
                        columnHeads={false}
                        columns={columns}
                        rows={rows}
                        rowKey={artifactId}
                        hasDetail={(row) => previewKindOf(row) !== null}
                        detail={previewOf}
                        expandLabel={(row, open) =>
                            open
                                ? LABELS.runs.hide_preview(artifactName(row, items))
                                : LABELS.runs.show_preview(artifactName(row, items))
                        }
                    />
                )}
            </PanelGroup>
        </div>
    )
}

/** What an artifact is called: its step, or the run, and the fan-out element that wrote it. */
function artifactName(row: ArtifactOut, items: ReadonlyMap<string, string>): string {
    const step = row.step_name ?? LABELS.runs.artifact_of_run
    const item = row.uri === null ? undefined : items.get(row.uri)
    return item === undefined ? step : LABELS.runs.artifact_of_item(step, item)
}

/** The artifact columns: the step, with its element and where it was written, and the size. */
function artifactColumns(
    prefix: string | null,
    items: ReadonlyMap<string, string>,
): DataColumn<ArtifactOut>[] {
    return [
        {
            id: 'artifact',
            header: LABELS.word.step.label,
            width: 'minmax(0,1fr)',
            cell: (row) => (
                <span className="flex min-w-0 flex-col gap-0.5 py-1">
                    <span className="flex min-w-0 items-baseline gap-2">
                        {prefix === null ? (
                            <span className="truncate text-sm">
                                {row.step_name ?? LABELS.runs.artifact_of_run}
                            </span>
                        ) : (
                            <TextLink
                                variant="data"
                                className="truncate text-sm"
                                href={artifactUrl(prefix, row.id)}
                                download
                            >
                                {row.step_name ?? LABELS.runs.artifact_of_run}
                            </TextLink>
                        )}
                        {row.uri !== null && items.get(row.uri) !== undefined && (
                            <span className="font-mono text-xs text-faint">{items.get(row.uri)}</span>
                        )}
                    </span>
                    {/* A row with no uri inlined on the run, and has no location to state. */}
                    {row.uri !== null && (
                        <span className="identifier truncate" title={row.uri}>
                            {shortenUri(row.uri)}
                        </span>
                    )}
                </span>
            ),
        },
        {
            id: 'size',
            header: LABELS.word.size,
            width: 'content',
            align: 'end',
            cell: (row) => (
                <span className="text-xs text-muted-foreground">{formatBytes(row.size_bytes)}</span>
            ),
        },
    ]
}

/** What reading an artifact's content for its preview has come to. */
type Read = { text: string } | { problem: Problem }

/** One artifact's content, drawn for its kind, read when its row is opened. */
function ArtifactPreview({ row, kind, name }: { row: ArtifactOut; kind: PreviewKind; name: string }) {
    const [read, setRead] = useState<Read | null>(null)

    useEffect(() => {
        let cancelled = false
        void readArtifactText(row.id).then(
            (text) => {
                if (!cancelled) setRead({ text })
            },
            (error: unknown) => {
                if (!cancelled) setRead({ problem: refusalOf(error) })
            },
        )
        return () => {
            cancelled = true
        }
    }, [row.id])

    return (
        <div className="py-2" data-artifact-preview={row.id}>
            {read === null ? (
                <p className="text-xs text-muted-foreground">{LABELS.shell.reading}</p>
            ) : 'problem' in read ? (
                <ProblemLine>{refusalLine(read.problem)}</ProblemLine>
            ) : (
                <FilePreview
                    name={name}
                    kind={kind}
                    text={read.text}
                    language={kind === 'text' ? previewLanguageOf(row.content_type) : undefined}
                    words={FILE_PREVIEW_WORDS}
                />
            )}
        </div>
    )
}
