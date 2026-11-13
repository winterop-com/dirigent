import { useMemo, useState, type ReactNode } from 'react'

import type { GraphControls } from '@winterop-com/sokkel-ui-graph/GraphCanvas'
import type { GraphLayoutChoice } from '@winterop-com/sokkel-ui-graph/GraphLayoutMenu'
import { PipelineGraph } from '@winterop-com/sokkel-ui-graph/PipelineGraph'
import { GraphPanel } from '@/components/graph/GraphPanel'
import { ViewTools } from '@/components/graph/ViewTools'
import { GRAPH_WORDS } from '@/lib/library-words'
import { FIT_MIN_ZOOM, GRAPH_LAYOUT, TALL_FIT, WRAP_WIDTH } from '@/lib/graph-view'
import { shapeSteps, type StepShape } from '@/lib/pipelines'

/**
 * A pipeline's graph on its own page, drawn by sokkel-ui-graph's `PipelineGraph` from the steps
 * `shapeSteps` reduces the current version's shape to: every step and every dependency, as tall as
 * its drawing, with the same graph in a window.
 *
 * It draws the shape and nothing that happened to it, so a box carries no state; choosing one is
 * the page's to answer. The canvas draws no buttons of its own: it hands its zoom and fit out, and
 * the panel's head on the page, and the window's corner, carry them beside the layout menu. The
 * layout a reader chooses lasts as long as the page does.
 */
export function ShapeGraph({
    name,
    steps,
    selected,
    onSelect,
    children,
}: {
    /** The pipeline's code, which the window is titled by. */
    name: string
    steps: readonly StepShape[]
    selected: string | null
    onSelect: (step: string | null) => void
    /** What stands under the graph in its panel. */
    children?: ReactNode
}) {
    const [layout, setLayout] = useState<GraphLayoutChoice>(GRAPH_LAYOUT)
    const [onPage, setOnPage] = useState<GraphControls | null>(null)
    const [inWindow, setInWindow] = useState<GraphControls | null>(null)
    const drawn = useMemo(() => shapeSteps(steps), [steps])

    const canvas = (frame: string) => {
        const windowed = frame === 'window'
        return (
            <PipelineGraph
                steps={drawn}
                selected={selected}
                onSelect={onSelect}
                frame={windowed ? 'stage' : 'fitted'}
                controls={false}
                onControls={windowed ? setInWindow : setOnPage}
                direction={layout.direction}
                routing={layout.routing}
                spacing={layout.spacing}
                fitMinZoom={FIT_MIN_ZOOM}
                tallFit={TALL_FIT}
                narrowFit
                wrapWidth={WRAP_WIDTH}
                wrapToCanvas
                words={GRAPH_WORDS}
            />
        )
    }
    return (
        <GraphPanel
            name={name}
            frame="fitted"
            tools={<ViewTools controls={onPage} frame="fitted" layout={layout} onLayout={setLayout} />}
            windowTools={
                <ViewTools controls={inWindow} frame="window" layout={layout} onLayout={setLayout} />
            }
            canvas={canvas}
            className="mt-6"
        >
            {children}
        </GraphPanel>
    )
}
