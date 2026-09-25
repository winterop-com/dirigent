import { useEffect, useMemo, useState } from 'react'

import {
    layoutDag,
    placedByRank,
    signatureOf,
    type ElkEngine,
    type LayoutShape,
    type PlacedGraph,
} from '@/lib/dag-layout'
import { whenIdle } from '@/lib/idle'

/**
 * The one door to elk, and the one place a canvas asks it for geometry.
 *
 * ONE DYNAMIC IMPORT, ONE CHUNK. The engine is larger than the rest of this bundle, so it is
 * fetched the first time a canvas asks for a layout rather than with the graph screens, and the
 * one worker it starts serves every canvas for the life of the tab.
 *
 * IT IS WARMED WHILE NOBODY IS WAITING. `warmLayout` is that same import, fired once the
 * browser is idle, so the first canvas of a session is placed against a worker already running.
 * A warm that fails costs nothing: the next canvas asks again.
 *
 * NOTHING WAITS ON IT TO DRAW. `placedByRank` is the shape placed by hand, which is what a
 * canvas shows until elk answers and what it keeps showing if elk never does. A placement
 * already answered stays on screen while the next is computed, so an edited document moves its
 * boxes once rather than twice.
 *
 * LAYOUT IS RECOMPUTED ON THE SHAPE, NOT ON THE STATE. A step going from running to succeeded
 * moves nothing, and neither does typing into its config, so the elk call is keyed on the
 * signature of the shape rather than on the object -- otherwise every frame of a live run, and
 * every keystroke in the editor, would re-place the whole canvas.
 */
const load = () => import('@/components/graph/elk-engine')

/** The engine this tab is placing with, or null until a canvas has asked for one. */
let engine: Promise<ElkEngine> | null = null

/** Whether the chunk has already been asked for, because asking twice warms nothing. */
let warmed = false

function elkEngine(): Promise<ElkEngine> {
    engine ??= load()
        .then((module) => module.newElk())
        .catch((reason: unknown) => {
            // A chunk that never arrived is asked for again by the next canvas.
            engine = null
            throw reason
        })
    return engine
}

/** Fetch elk's chunk and start its worker while the browser has nothing better to do. */
export function warmLayout(): void {
    if (warmed) return
    warmed = true
    whenIdle(() => {
        void elkEngine().catch(() => undefined)
    })
}

/** Place a shape, drawn by rank until elk has answered. */
export function usePlacedGraph(shape: LayoutShape): PlacedGraph {
    const [placed, setPlaced] = useState<PlacedGraph | null>(null)
    const signature = signatureOf(shape)

    useEffect(() => {
        let current = true
        void elkEngine()
            .then((elk) => layoutDag(shape, elk))
            .then(
                (result) => {
                    if (current) setPlaced(result)
                },
                () => {
                    // elk refused this graph, or never arrived. The canvas keeps the placement
                    // it is drawing and the panel still holds every step.
                },
            )
        return () => {
            current = false
        }
        // The geometry is a function of the shape alone, which is what `signature` states.
        // oxlint-disable-next-line react/exhaustive-deps
    }, [signature])

    // oxlint-disable-next-line react/exhaustive-deps
    const rough = useMemo(() => placedByRank(shape), [signature])

    return placed ?? rough
}
