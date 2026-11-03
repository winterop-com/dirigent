import { type Edge } from '@xyflow/react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { GraphCanvas, LayoutControl, type CanvasFrame } from '@/components/graph/GraphCanvas'
import { GraphPanel } from '@/components/graph/GraphPanel'
import { measuresByFont, useMeasure } from '@/components/graph/measure'
import { usePlacedGraph } from '@/components/graph/use-placed'
import { StepNode, type StepNode as StepNodeKind } from '@/components/run/StepNode'
import { usePrefersReducedMotion } from '@/hooks/use-reduced-motion'
import {
    DEFAULT_LAYOUT,
    drawnSize,
    type LayoutChoice,
    type LayoutShape,
    type Measure,
} from '@/lib/dag-layout'
import { runNodeSize } from '@/lib/node-size'
import { drawnStates, edgeClasses, handovers, type StepView } from '@/lib/run-detail'
import type { AnyStatus } from '@/lib/status'
import type { DagView } from '@/lib/runs'

/**
 * The run's graph: the pinned definition, with what each step has amounted to on it.
 *
 * ITS EDGES CARRY WHERE THE RUN WENT. An edge takes a whisper of the state its source settled
 * in and is dashed into a step that never happened; what that amounts to is `edgeTone`, and
 * the hues are mixed toward the resting stroke in index.css.
 *
 * AND WHILE THE RUN IS LIVE, THEY CARRY IT MOVING. An edge out of a step that has produced its
 * output into one still reading it is dashed and travelling; the moment a step succeeds, each
 * edge into a step that could still read it plays one handover. `edgeMotion` decides both, and
 * a terminal run moves nowhere. The nodes gain nothing from any of it.
 *
 * IT IS A VIEW, NOT AN EDITOR. A pipeline is edited on its own screen, against the document;
 * this canvas selects a step and nothing else.
 *
 * This module is loaded lazily. React Flow is a large part of what this page costs, and the
 * screens that draw a graph are the only ones that pay for it; elk is a chunk of its own and
 * is fetched when this canvas asks for geometry.
 */

/**
 * The one node kind this graph draws. Built once: React Flow re-mounts every node on a new
 * object. `nodeTypes` and `type` are React Flow's own words for it and are its to fix.
 */
const NODE_TYPES = { step: StepNode }

/** How long a handover is drawn for, which is the length of the keyframes in index.css. */
const HANDOVER_MS = 600

/** No step is handing anything over, held once so a still graph re-renders nothing. */
const NONE: ReadonlySet<string> = new Set()

/**
 * The steps whose output has just landed, for as long as their handover is being drawn.
 *
 * IT IS A COMPARISON BETWEEN RENDERS, NOT AN EVENT. The stream says a step succeeded and
 * nothing says when its output was stored, so the instant a handover is drawn at is the render
 * that moved the step there -- `handovers` is that comparison, and this holds its answer for as
 * long as the animation lasts.
 */
function useHandovers(views: readonly StepView[]): ReadonlySet<string> {
    const [handing, setHanding] = useState<ReadonlySet<string>>(NONE)
    const before = useRef<Map<string, AnyStatus>>(new Map())
    const timers = useRef<number[]>([])

    useEffect(() => {
        const fresh = handovers(before.current, views)
        before.current = drawnStates(views)
        if (fresh.length === 0) return
        setHanding((held) => new Set([...held, ...fresh]))
        // The timer is not this effect's to clean up: the screen ticks a clock every second, so
        // a cleanup here would cancel every handover before it had been drawn.
        timers.current.push(
            window.setTimeout(() => {
                setHanding((held) => new Set([...held].filter((step) => !fresh.includes(step))))
            }, HANDOVER_MS),
        )
    }, [views])

    useEffect(() => {
        const pending = timers.current
        return () => {
            for (const timer of pending) window.clearTimeout(timer)
        }
    }, [])

    return handing
}

/** The run's graph reduced to what elk needs: an id, a width and a height per step, and the pairs. */
function shapeOf(dag: DagView, views: readonly StepView[], measure: Measure): LayoutShape {
    const byCode = new Map(views.map((view) => [view.node.code, view]))
    return {
        nodes: dag.nodes.flatMap((node) => {
            const view = byCode.get(node.code)
            return view === undefined ? [] : [{ id: node.code, ...runNodeSize(view, measure) }]
        }),
        edges: dag.edges,
    }
}

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
    const [layout, setLayout] = useState<LayoutChoice>(DEFAULT_LAYOUT)
    const measure = useMeasure()
    const shape = useMemo(() => shapeOf(dag, views, measure), [dag, views, measure])
    const placed = usePlacedGraph(shape, layout)
    const byCode = useMemo(() => new Map(views.map((view) => [view.node.code, view])), [views])

    const nodes = useMemo<StepNodeKind[]>(() => {
        return placed.nodes.flatMap((node) => {
            const view = byCode.get(node.id)
            if (view === undefined) return []
            return [
                {
                    id: node.id,
                    type: 'step' as const,
                    position: { x: node.x, y: node.y },
                    width: node.width,
                    height: node.height,
                    measured: drawnSize(node),
                    selected: node.id === selected,
                    draggable: false,
                    data: { view },
                },
            ]
        })
    }, [byCode, placed, selected])

    const handing = useHandovers(views)
    const reduced = usePrefersReducedMotion()

    const edges = useMemo<Edge[]>(() => {
        return placed.edges.map((edge) => ({
            id: edge.id,
            source: edge.source,
            target: edge.target,
            className: edgeClasses(byCode.get(edge.source), byCode.get(edge.target), { handing, reduced }),
            data: { points: edge.points },
        }))
    }, [byCode, handing, placed, reduced])

    const canvas = (frame: CanvasFrame) => (
        <GraphCanvas
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onSelect={onSelect}
            frame={frame}
            layout={layout}
            settled={placed.settled && measuresByFont(measure)}
            control={frame === 'window' ? <LayoutControl layout={layout} onLayout={setLayout} /> : undefined}
        />
    )
    return <GraphPanel name={name} frame="filled" layout={layout} onLayout={setLayout} canvas={canvas} />
}
