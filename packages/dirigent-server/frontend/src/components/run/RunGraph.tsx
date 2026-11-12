import { useMemo, useState, type ReactNode } from 'react'

import type { GraphControls } from '@winterop-com/sokkel-ui-graph/GraphCanvas'
import { GraphLayoutMenu, type GraphLayoutChoice } from '@winterop-com/sokkel-ui-graph/GraphLayoutMenu'
import { RunGraph as RunCanvas } from '@winterop-com/sokkel-ui-graph/RunGraph'
import type { GraphRouting } from '@winterop-com/sokkel-ui-graph/layout'
import { IconButton } from '@winterop-com/sokkel-ui/IconButton'
import { GraphPanel } from '@/components/graph/GraphPanel'
import { WRAP_WIDTH } from '@/lib/dag-layout'
import { GRAPH_LAYOUT_WORDS, GRAPH_WORDS } from '@/lib/design-system'
import { formatDuration } from '@/lib/format'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
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

/** What the run's graph opens on. */
export const RUN_LAYOUT: GraphLayoutChoice = { direction: 'right', routing: 'orthogonal', spacing: 'normal' }

/** The edges the run's layout menu offers. */
const ROUTINGS: readonly GraphRouting[] = ['orthogonal', 'splines']

/** The least zoom a fit of the run's graph goes to, at every width. */
const FIT_MIN_ZOOM = 0.8

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
    const [layout, setLayout] = useState<GraphLayoutChoice>(RUN_LAYOUT)
    const [onPage, setOnPage] = useState<GraphControls | null>(null)
    const [inWindow, setInWindow] = useState<GraphControls | null>(null)
    const steps = useMemo(() => runSteps(dag, views), [dag, views])

    const menu = (
        <GraphLayoutMenu
            value={layout}
            onValueChange={setLayout}
            routings={ROUTINGS}
            words={GRAPH_LAYOUT_WORDS}
            closeOnChoice
            trigger={
                <IconButton label={LABELS.shell.layout.menu} size="icon-sm" className="text-muted-foreground">
                    <ICONS.graph_layout aria-hidden />
                </IconButton>
            }
        />
    )
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
                narrowFit={false}
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
            tools={<ViewTools controls={onPage} filled menu={menu} />}
            windowTools={<ViewTools controls={inWindow} filled={false} menu={menu} />}
            canvas={canvas}
        />
    )
}

/**
 * Zoom out, zoom in and fit for the canvas that handed out `controls`, then the layout menu. On
 * the page, where the wheel zooms the canvas too, the zoom buttons' tooltips say so.
 */
function ViewTools({
    controls,
    filled,
    menu,
}: {
    controls: GraphControls | null
    filled: boolean
    menu: ReactNode
}) {
    return (
        <span className="flex items-center gap-0.5 font-normal">
            {controls !== null && !controls.empty && (
                <>
                    <IconButton
                        label={LABELS.shell.zoom_out}
                        tooltip={filled ? LABELS.shell.zoom_out_filled : undefined}
                        size="icon-sm"
                        className="text-muted-foreground"
                        onClick={controls.zoomOut}
                    >
                        <ICONS.zoom_out aria-hidden />
                    </IconButton>
                    <IconButton
                        label={LABELS.shell.zoom_in}
                        tooltip={filled ? LABELS.shell.zoom_in_filled : undefined}
                        size="icon-sm"
                        className="text-muted-foreground"
                        onClick={controls.zoomIn}
                    >
                        <ICONS.zoom_in aria-hidden />
                    </IconButton>
                    <IconButton
                        label={LABELS.shell.fit_view}
                        size="icon-sm"
                        className="text-muted-foreground"
                        onClick={controls.fit}
                    >
                        <ICONS.fit_view aria-hidden />
                    </IconButton>
                </>
            )}
            {menu}
        </span>
    )
}
