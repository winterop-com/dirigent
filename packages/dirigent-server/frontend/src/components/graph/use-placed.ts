/**
 * Where elk is loaded, and the one place a canvas asks it for geometry.
 *
 * LAYOUT IS RECOMPUTED ON THE SHAPE, NOT ON THE STATE. A step going from running to succeeded
 * moves nothing, and neither does typing into its config, so the elk call is keyed on the
 * signature of the shape rather than on the object -- otherwise every frame of a live run, and
 * every keystroke in the editor, would re-place the whole canvas.
 *
 * This module and `GraphCanvas` are imported only from lazy chunks: elk and React Flow together
 * are a larger download than the rest of this bundle, and only the graph screens pay for them.
 */

import ELK from 'elkjs/lib/elk.bundled.js'
import { useEffect, useState } from 'react'

import { layoutDag, signatureOf, type LayoutShape, type PlacedGraph } from '@/lib/dag-layout'

/** One elk for the life of the tab. It holds no graph between calls. */
const elk = new ELK()

/** Place a shape, answering null until elk has. */
export function usePlacedGraph(shape: LayoutShape): PlacedGraph | null {
    const [placed, setPlaced] = useState<PlacedGraph | null>(null)
    const signature = signatureOf(shape)

    useEffect(() => {
        let current = true
        void layoutDag(shape, elk).then(
            (result) => {
                if (current) setPlaced(result)
            },
            () => {
                // elk refused this graph. The panel still holds every step; the canvas stays
                // empty rather than the screen failing.
            },
        )
        return () => {
            current = false
        }
        // The geometry is a function of the shape alone, which is what `signature` states.
        // oxlint-disable-next-line react/exhaustive-deps
    }, [signature])

    return placed
}
