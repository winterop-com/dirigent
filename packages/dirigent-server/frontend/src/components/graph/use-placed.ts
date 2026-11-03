import { useEffect, useMemo, useState } from 'react'

import { elkEngine } from '@/components/graph/elk'
import {
    DEFAULT_LAYOUT,
    layoutDag,
    placedByRank,
    signatureOf,
    type LayoutChoice,
    type LayoutShape,
    type PlacedGraph,
} from '@/lib/dag-layout'

/**
 * The one place a canvas asks elk for geometry.
 *
 * NOTHING WAITS ON ELK TO DRAW. `placedByRank` is the shape placed by hand, which is what a
 * canvas shows until elk answers and what it keeps showing if elk never does. A placement
 * already answered stays on screen while the next is computed, so an edited document moves its
 * boxes once rather than twice.
 *
 * LAYOUT IS RECOMPUTED ON THE SHAPE, NOT ON THE STATE. A step going from running to succeeded
 * moves nothing, and neither does typing into its config, so the elk call is keyed on the
 * signature of the shape rather than on the object -- otherwise every frame of a live run, and
 * every keystroke in the editor, would re-place the whole canvas. A view's layout choice is part
 * of that signature.
 */
export function usePlacedGraph(shape: LayoutShape, choice: LayoutChoice = DEFAULT_LAYOUT): PlacedGraph {
    const [placed, setPlaced] = useState<PlacedGraph | null>(null)
    const signature = signatureOf(shape, choice)

    useEffect(() => {
        let current = true
        void elkEngine()
            .then((elk) => layoutDag(shape, elk, choice))
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
        // The geometry is a function of the shape and the choice alone, which is what `signature` states.
        // oxlint-disable-next-line react/exhaustive-deps
    }, [signature])

    // One signature, one rough placement: what it is placed from is the shape alone.
    // oxlint-disable-next-line react/exhaustive-deps
    const rough = useMemo(() => placedByRank(shape, choice), [signature])

    return placed ?? rough
}
