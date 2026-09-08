import { useCallback, useMemo } from 'react'

import { PageState } from '@/components/PageState'
import { PipelineTab } from '@/components/pipeline/PipelineTab'
import { useRead } from '@/hooks/use-read'
import { readCatalog } from '@/lib/blocks'
import { readConnections } from '@/lib/connections'
import { readPipeline, readVersions, type PipelineOut } from '@/lib/pipelines'
import { unmetIn } from '@/lib/requirements'
import { EVERY_RUN, readRuns } from '@/lib/runs'

/** How many versions this pane carries. */
const RECENT_VERSIONS = 5

/** How many recent runs this pane carries. */
const RECENT_RUNS = 3

/**
 * One pipeline read beside the listing, without leaving it.
 *
 * IT IS THE EDITOR'S OWN PANE. What a reader wants of a row -- what it takes, what it reaches,
 * what it requires, what fires it, how it has been running, what has been applied -- is what
 * `PipelineTab` already answers, so this reads what that pane is handed rather than growing a
 * second rendering of the same six sections that could disagree with it.
 *
 * THE DOCUMENT IS THE STORED ONE. There is nothing being edited here, so the parameters and the
 * triggers are read from the version the instance holds, which is what the row is about.
 *
 * IT IS FETCHED WHEN A ROW IS CHOSEN. The listing is in the entry chunk every reader pays for,
 * and the pane behind it brings the schema reader, the markdown lexer and the requirements
 * check; a reader who never opens a row downloads none of it.
 */
export function PipelinePreview({ pipeline }: { pipeline: PipelineOut }) {
    const code = pipeline.code

    const detail = useRead(useCallback(() => readPipeline(code), [code]))
    const versions = useRead(useCallback(() => readVersions(code, RECENT_VERSIONS), [code]))
    const runs = useRead(
        useCallback(() => readRuns({ ...EVERY_RUN, pipeline: code }, null, RECENT_RUNS), [code]),
    )
    // Neither is this pipeline's, so neither is re-read when another row is chosen.
    const connections = useRead(readConnections)
    const catalog = useRead(readCatalog)

    const document = detail.value?.document ?? null

    // Null until each read lands: an unread catalog is not an empty one, and a pane that said
    // "not installed" for the half second before it arrives teaches a reader to disbelieve it.
    const installed = useMemo(() => {
        const blocks = catalog.value?.blocks ?? []
        return blocks.length === 0 ? null : blocks.map((block) => block.id)
    }, [catalog.value])
    const held = useMemo(() => connections.value?.items.map((one) => one.code) ?? null, [connections.value])
    const unmet = useMemo(() => unmetIn(document, installed, held), [document, held, installed])

    const reading = !detail.read || !versions.read || !runs.read

    if (reading || detail.value === null) {
        return (
            <div className="p-4">
                <PageState loading={reading} problem={detail.problem} empty={false}>
                    {null}
                </PageState>
            </div>
        )
    }

    return (
        <PipelineTab
            pipeline={detail.value}
            document={document}
            versions={versions.value?.items ?? []}
            connections={connections.value?.items ?? null}
            runs={runs.value?.items ?? []}
            unmet={unmet}
        />
    )
}
