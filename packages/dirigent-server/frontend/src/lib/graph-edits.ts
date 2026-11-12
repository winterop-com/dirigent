/**
 * What a gesture on the editor's canvas does to the document.
 *
 * AN EDGE IS A `depends_on` ENTRY. Drawing one between two boxes and choosing one from the chip
 * list in the step's own pane are the same edit against the same local document, so both end in
 * `withDependsOn` and the graph holds no state of its own. Drawing an edge the document already
 * has is not an edit: `withEdge` answers with the document it was given, and the store publishes
 * nothing.
 *
 * A CYCLE IS REFUSED BEFORE IT IS DRAWN. A pipeline is a DAG and `$apply` refuses one that is
 * not, but a canvas that accepted the gesture and only said so on the next apply would answer a
 * pointer with a round trip. What this decides is the same thing the server decides, and it
 * names the steps that close the loop rather than saying that something is wrong.
 */

import { cyclePath, type StepNeeds } from '@winterop-com/sokkel-ui-graph/cycles'
import type { JsonMap } from '@/lib/api'
import { LABELS } from '@/lib/labels'
import { dependsOn, edgesIn, stepNames, stepsIn, withDependsOn } from '@/lib/pipeline-document'

/** A document where `to` waits for `from`, or the same document when it already did. */
export function withEdge(document: JsonMap, from: string, to: string): JsonMap {
    const held = dependsOn(document, to)
    if (held.includes(from)) return document
    return withDependsOn(document, to, [...held, from])
}

/** A document where `to` no longer waits for `from`, or the same document when it did not. */
export function withoutEdge(document: JsonMap, from: string, to: string): JsonMap {
    const held = dependsOn(document, to)
    if (!held.includes(from)) return document
    return withDependsOn(
        document,
        to,
        held.filter((one) => one !== from),
    )
}

/**
 * A document without one step, and without any reference to it.
 *
 * A STEP LEAVES NO EDGE BEHIND IT. A `depends_on` naming a step the document no longer declares
 * is what `$apply` refuses, so taking the step out takes its name out of every other step's
 * prerequisites in the same edit.
 */
export function withoutStep(document: JsonMap, step: string): JsonMap {
    const steps = stepsIn(document)
    if (!(step in steps)) return document

    const kept = Object.fromEntries(Object.entries(steps).filter(([name]) => name !== step))
    let left: JsonMap = { ...document, steps: kept }
    for (const name of Object.keys(kept)) {
        const held = dependsOn(left, name)
        if (!held.includes(step)) continue
        left = withDependsOn(
            left,
            name,
            held.filter((one) => one !== step),
        )
    }
    return left
}

/** The document's steps as a loop is told from: each step's key and the keys it waits for. */
export function stepNeeds(document: JsonMap | null): StepNeeds[] {
    const needs = new Map<string, string[]>()
    for (const [from, to] of edgesIn(document)) needs.set(to, [...(needs.get(to) ?? []), from])
    return stepNames(document).map((code) => ({ code, needs: needs.get(code) ?? [] }))
}

/**
 * Why an edge from `from` to `to` is refused, naming the shortest loop it would close the way the
 * pipeline runs -- `report → parse → report` -- or null when it closes none.
 */
export function cycleRefusal(steps: readonly StepNeeds[], from: string, to: string): string | null {
    const loop = cyclePath(steps, from, to)
    if (loop === null) return null
    return LABELS.editor.canvas.cycle_refused(to, from, [...loop, to].join(' → '))
}
