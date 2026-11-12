import { useMemo, useState } from 'react'

import { RunGraph as RunCanvas } from '@winterop-com/sokkel-ui-graph/RunGraph'
import type { GraphRouting, GraphSpacing } from '@winterop-com/sokkel-ui-graph/layout'
import { IconButton } from '@winterop-com/sokkel-ui/IconButton'
import { GraphPanel } from '@/components/graph/GraphPanel'
import { LayoutMenu, type RoutingOption } from '@/components/graph/LayoutMenu'
import type { LayoutDirection, LayoutSpacing } from '@/lib/dag-layout'
import { GRAPH_WORDS } from '@/lib/design-system'
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
 * This module is loaded lazily: React Flow is a large part of what this page costs, and elk is a
 * chunk of its own fetched when the canvas asks for geometry.
 */

/** How the run's graph is laid out: the direction, the library's routing and the spacing. */
export interface RunLayout {
    direction: LayoutDirection
    routing: GraphRouting
    spacing: LayoutSpacing
}

/** What the run's graph opens on. */
export const RUN_LAYOUT: RunLayout = { direction: 'right', routing: 'orthogonal', spacing: 'default' }

/** The edges the run's layout menu offers. */
const ROUTINGS: readonly RoutingOption<GraphRouting>[] = [
    ['orthogonal', LABELS.shell.layout.orthogonal],
    ['splines', LABELS.shell.layout.splines],
]

/** The library's spacing for this app's choice. */
const SPACING: Record<LayoutSpacing, GraphSpacing> = { default: 'normal', compact: 'compact', roomy: 'roomy' }

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
    const [layout, setLayout] = useState<RunLayout>(RUN_LAYOUT)
    const steps = useMemo(() => runSteps(dag, views), [dag, views])

    const menu = (
        <LayoutMenu
            choice={layout}
            onChoose={setLayout}
            routings={ROUTINGS}
            trigger={
                <IconButton label={LABELS.shell.layout.menu} size="icon-sm" className="text-muted-foreground">
                    <ICONS.graph_layout aria-hidden />
                </IconButton>
            }
        />
    )
    const canvas = () => (
        <RunCanvas
            steps={steps}
            selected={selected}
            onSelect={onSelect}
            frame="stage"
            direction={layout.direction}
            routing={layout.routing}
            spacing={SPACING[layout.spacing]}
            formatDuration={formatDuration}
            words={GRAPH_WORDS}
        />
    )
    return <GraphPanel name={name} frame="filled" tools={menu} windowTools={menu} canvas={canvas} />
}
