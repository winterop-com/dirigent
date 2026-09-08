/**
 * What a document needs that this instance has not got.
 *
 * A DOCUMENT IS PORTABLE AND AN INSTANCE IS NOT. The same pipeline is applied to a laptop, a
 * staging box and a cluster, and the blocks and connections it reaches are whatever each of
 * those has installed and configured. So a document can be perfectly valid here and fail at
 * its second step there, and the place to say so is the screen somebody is about to press Run
 * on -- not the run's error afterwards.
 *
 * THE ANSWER IS A DECISION, NOT MARKUP. Catalog and document in, conditions out: the chip on
 * the overview tab, the word on the connections row, the line in the run dialog and the mark
 * on the graph node are four renderings of this one answer, and none of them decides anything.
 *
 * NOTHING IS MISSING WHILE A READ IS PENDING. `null` for the catalog or the connections means
 * this bundle has not been told yet, and an unread catalog must never be reported as an empty
 * one -- a screen that shouted "not installed" at every step for the half second before the
 * catalog landed would teach a reader to ignore it.
 */

import type { JsonMap } from '@/lib/api'
import { blockOf, stepsIn, stepNames } from '@/lib/pipeline-document'

/** One step whose block this instance does not publish. */
export interface MissingStep {
    step: string
    block: string
}

/** Everything a document names that this instance has not got. */
export interface Unmet {
    /** Steps whose block the catalog does not publish, in the order the document declares them. */
    steps: MissingStep[]
    /** Blocks named under `requires.blocks` that the catalog does not publish. */
    blocks: string[]
    /** Connections the document names that this instance does not hold. */
    connections: string[]
}

const NOTHING: Unmet = { steps: [], blocks: [], connections: [] }

/**
 * What one document needs that this instance has not got.
 *
 * `catalog` is every block id this instance publishes and `held` is every connection code it
 * holds; either being null is a read that has not landed, and nothing is claimed missing on
 * the strength of a read nobody has made.
 */
export function unmetIn(
    document: JsonMap | null,
    catalog: readonly string[] | null,
    held: readonly string[] | null,
): Unmet {
    if (document === null) return NOTHING
    const installed = catalog === null ? null : new Set(catalog)
    const configured = held === null ? null : new Set(held)

    const steps =
        installed === null
            ? []
            : stepNames(document).flatMap((step) => {
                  const block = blockOf(document, step)
                  if (block === null || installed.has(block)) return []
                  return [{ step, block }]
              })

    const blocks = installed === null ? [] : requiredBlocks(document).filter((one) => !installed.has(one))

    const connections =
        configured === null ? [] : connectionsNamed(document).filter((name) => !configured.has(name))

    return { steps, blocks, connections }
}

/** Whether anything at all is unmet, which is what decides whether a warning is drawn. */
export function anythingUnmet(unmet: Unmet): boolean {
    return unmet.steps.length > 0 || unmet.blocks.length > 0 || unmet.connections.length > 0
}

/**
 * What a reader about to start a run is told, one line per thing that will go wrong.
 *
 * A step is named with the block behind it, because "not installed" without the step is a fact
 * nobody can act on, and the step is where the run will actually stop.
 */
export function unmetLines(unmet: Unmet): string[] {
    return [
        ...unmet.steps.map((one) => `this run will fail at ${one.step}: ${one.block} is not installed`),
        ...unmet.blocks
            .filter((block) => !unmet.steps.some((one) => one.block === block))
            .map((block) => `this document requires ${block}, which is not installed`),
        ...unmet.connections.map((name) => `the connection ${name} is not configured on this instance`),
    ]
}

/** Whether one step's block is among the missing, which is what marks a node on the graph. */
export function stepMissing(unmet: Unmet, step: string): boolean {
    return unmet.steps.some((one) => one.step === step)
}

/** Whether one required block is among the missing, which is what makes its chip critical. */
export function blockMissing(unmet: Unmet, block: string): boolean {
    return unmet.blocks.includes(block)
}

/** Whether one named connection is among the missing, which is what the connections row says. */
export function connectionMissing(unmet: Unmet, name: string): boolean {
    return unmet.connections.includes(name)
}

/** The blocks a document states it needs of an instance, under `requires.blocks`. */
export function requiredBlocks(document: JsonMap | null): string[] {
    return stringsAt(mapAt(document, 'requires'), 'blocks')
}

/**
 * The connections a document names.
 *
 * `requires.connections` is what a document states it needs, and a step naming one in its
 * config is what it actually reaches, so both are read: a document may name a connection it
 * forgot to require, and that one will fail at run just the same.
 */
export function connectionsNamed(document: JsonMap | null): string[] {
    const required = stringsAt(mapAt(document, 'requires'), 'connections')
    const used = Object.values(stepsIn(document)).flatMap((step) => {
        const config = mapAt(step, 'config')
        return ['connection', 'sign_with'].flatMap((key) => {
            const value = config === null ? undefined : config[key]
            return typeof value === 'string' ? [value] : []
        })
    })
    return [...new Set([...required, ...used])]
}

/** The pipelines a document states it needs, which no read here can check. */
export function requiredPipelines(document: JsonMap | null): string[] {
    return stringsAt(mapAt(document, 'requires'), 'pipelines')
}

function mapAt(value: JsonMap | null, key: string): JsonMap | null {
    const found = value?.[key]
    if (found === null || found === undefined || typeof found !== 'object' || Array.isArray(found)) return null
    return found as JsonMap
}

function stringsAt(value: JsonMap | null, key: string): string[] {
    const found = value?.[key]
    if (!Array.isArray(found)) return []
    return (found as unknown[]).flatMap((one) => (typeof one === 'string' ? [one] : []))
}
