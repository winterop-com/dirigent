import { useMemo, useState } from 'react'

import type { GraphControls } from '@winterop-com/sokkel-ui-graph/GraphCanvas'
import type { GraphLayoutChoice } from '@winterop-com/sokkel-ui-graph/GraphLayoutMenu'
import { RunGraph as RunCanvas } from '@winterop-com/sokkel-ui-graph/RunGraph'
import { GraphPanel } from '@/components/graph/GraphPanel'
import { ViewTools } from '@/components/graph/ViewTools'
import { GRAPH_WORDS } from '@/lib/design-system'
import { formatDuration } from '@/lib/format'
import { FIT_MIN_ZOOM, GRAPH_LAYOUT, TALL_FIT, WRAP_WIDTH } from '@/lib/graph-view'
import { runSteps, type StepView } from '@/lib/run-detail'
import type { DagView } from '@/lib/runs'

/**
 * The run's graph: the pinned definition, with what each step has amounted to on it, drawn by
 * sokkel-ui-graph's `RunGraph` from the steps `runSteps` reduces the run to.
 *
 * The library derives each edge from the states of its two ends -- the hue its source settled in,
 * dashed into a skipped step, travelling while a step that has produced feeds one still running,
 * one pulse when a step it saw produce hands over -- and sizes each box so a step changing state
 * moves nothing. A canvas selects a step and nothing else.
 *
 * The canvas draws no buttons of its own: it hands its zoom and fit out, and the panel's head on
 * the page, and the window's corner, carry them beside the layout menu.
 *
 * This module is loaded lazily: React Flow is a large part of what this page costs, and elk is a
 * chunk of its own fetched when the canvas asks for geometry.
 */

/** The tallest the filled panel insists on for the drawing, which is less when the drawing is. */
const FILL_FLOOR = 240

/**
 * The run's graph in its panel on the run's page, filling the room the page leaves it, with the
 * same graph in a window. The layout a reader chooses lasts as long as this run's screen does.
 */
export function RunGraph({
    name,
    dag,
    views,
    selected,
    onSelect,
}: {
    /** The pipeline's code, which the window is titled by. */
    name: string
    dag: DagView
    views: StepView[]
    selected: string | null
    onSelect: (step: string | null) => void
}) {
    const [layout, setLayout] = useState<GraphLayoutChoice>(GRAPH_LAYOUT)
    const [onPage, setOnPage] = useState<GraphControls | null>(null)
    const [inWindow, setInWindow] = useState<GraphControls | null>(null)
    const steps = useMemo(() => runSteps(dag, views), [dag, views])

    const canvas = (frame: string) => {
        const windowed = frame === 'window'
        return (
            <RunCanvas
                steps={steps}
                selected={selected}
                onSelect={onSelect}
                frame={windowed ? 'stage' : 'filled'}
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
                fillFloor={FILL_FLOOR}
                formatDuration={formatDuration}
                words={GRAPH_WORDS}
            />
        )
    }
    return (
        <GraphPanel
            name={name}
            frame="filled"
            tools={<ViewTools controls={onPage} frame="filled" layout={layout} onLayout={setLayout} />}
            windowTools={
                <ViewTools controls={inWindow} frame="window" layout={layout} onLayout={setLayout} />
            }
            canvas={canvas}
        />
    )
}
