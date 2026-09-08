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

import type { JsonMap } from '@/lib/api'
import { dependsOn, edgesIn, stepsIn, withDependsOn } from '@/lib/pipeline-document'

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

/**
 * The loop an edge from `from` to `to` would close, or null when it closes none.
 *
 * The walk starts at the dependent and follows the document's own edges looking for the
 * prerequisite, so what comes back reads the way the pipeline runs -- `report → parse → report`
 * -- and it is the shortest such loop, because a message naming forty steps names none of them.
 */
export function cycleThrough(document: JsonMap | null, from: string, to: string): string[] | null {
    if (from === to) return [to, to]

    const forward = new Map<string, string[]>()
    for (const [source, target] of edgesIn(document)) {
        forward.set(source, [...(forward.get(source) ?? []), target])
    }

    const seen = new Set([to])
    let front: string[][] = [[to]]
    while (front.length > 0) {
        const next: string[][] = []
        for (const path of front) {
            for (const step of forward.get(path[path.length - 1] ?? '') ?? []) {
                if (step === from) return [...path, from, to]
                if (seen.has(step)) continue
                seen.add(step)
                next.push([...path, step])
            }
        }
        front = next
    }
    return null
}

/** Why an edge was refused, in the words of the steps that refuse it. */
export function cycleRefusal(from: string, to: string, cycle: string[]): string {
    return `${to} cannot wait for ${from}: that closes a loop, ${cycle.join(' → ')}`
}
