import { type Edge, type Node, type NodeProps } from '@xyflow/react'
import { useMemo, useState, type ReactNode } from 'react'

import { GraphCanvas, LayoutControl, type CanvasFrame } from '@/components/graph/GraphCanvas'
import { GraphPanel } from '@/components/graph/GraphPanel'
import { useMeasure } from '@/components/graph/measure'
import { StepPorts } from '@/components/graph/StepPorts'
import { usePlacedGraph } from '@/components/graph/use-placed'
import { DEFAULT_LAYOUT, drawnSize, NODE_HEIGHT, type LayoutChoice, type LayoutShape } from '@/lib/dag-layout'
import { headingOf } from '@/lib/identity'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { shapeNodeWidth } from '@/lib/node-size'
import type { StepShape } from '@/lib/pipelines'
import { cn } from '@/lib/utils'

/** What one box of a pipeline's graph carries. */
interface ShapeNodeData extends Record<string, unknown> {
    step: StepShape
}

type ShapeNodeKind = Node<ShapeNodeData, 'step'>

/** The title a box is headed by and the line under it, which are also what decide its width. */
function wordsOf(step: StepShape): { title: string; named: boolean; line: string } {
    const heading = headingOf(step)
    return {
        title: heading.title,
        named: heading.named,
        line: heading.code === null ? step.block : `${heading.code} · ${step.block}`,
    }
}

/** One step, as a box on the pipeline's own page: its title, and the block it runs under it. */
function ShapeNode({ data, selected }: NodeProps<ShapeNodeKind>) {
    const { step } = data
    const words = wordsOf(step)
    const source = step.kind === 'source'
    const line = source ? LABELS.editor.canvas.listens_to(words.line) : words.line
    return (
        <div className="step-node" data-selected={selected === true} data-source={source} title={line}>
            <StepPorts editable={false} />
            <div className="flex items-center gap-1.5">
                {source && <ICONS.source className="size-3 shrink-0 text-muted-foreground" aria-hidden />}
                <span
                    data-testid="step-title"
                    title={words.title}
                    className={cn('step-node-title truncate', !words.named && 'font-mono')}
                >
                    {words.title}
                </span>
                {step.fan_out && (
                    <ICONS.fan_out className="ml-auto size-3 shrink-0 text-muted-foreground" aria-hidden />
                )}
            </div>
            <span data-testid="step-line" className="truncate font-mono text-muted-foreground" title={line}>
                {words.line}
            </span>
        </div>
    )
}

const NODE_TYPES = { step: ShapeNode }

/**
 * A pipeline's graph on its own page: every step and every dependency, as tall as its drawing,
 * with the same graph in a window.
 *
 * It draws the current version's shape and nothing that happened to it, so a box carries no
 * state; choosing one is the page's to answer. The layout a reader chooses lasts as long as the
 * page does.
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
    const [layout, setLayout] = useState<LayoutChoice>(DEFAULT_LAYOUT)
    const measure = useMeasure()
    const shape = useMemo<LayoutShape>(
        () => ({
            nodes: steps.map((step) => ({
                id: step.code,
                width: shapeNodeWidth(wordsOf(step), step.kind === 'source', step.fan_out, measure),
                height: NODE_HEIGHT,
            })),
            edges: steps.flatMap((step) =>
                step.depends_on.map((from): [string, string] => [from, step.code]),
            ),
        }),
        [measure, steps],
    )
    const placed = usePlacedGraph(shape, layout)
    const byCode = useMemo(() => new Map(steps.map((step) => [step.code, step])), [steps])

    const nodes = useMemo<ShapeNodeKind[]>(
        () =>
            placed.nodes.flatMap((node) => {
                const step = byCode.get(node.id)
                if (step === undefined) return []
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
                        data: { step },
                    },
                ]
            }),
        [byCode, placed, selected],
    )
    const edges = useMemo<Edge[]>(
        () =>
            placed.edges.map((edge) => ({
                id: edge.id,
                source: edge.source,
                target: edge.target,
                data: { points: edge.points },
            })),
        [placed],
    )
    const canvas = (frame: CanvasFrame) => (
        <GraphCanvas
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onSelect={onSelect}
            frame={frame}
            layout={layout}
            control={frame === 'window' ? <LayoutControl layout={layout} onLayout={setLayout} /> : undefined}
        />
    )
    return (
        <GraphPanel
            name={name}
            frame="fitted"
            layout={layout}
            onLayout={setLayout}
            canvas={canvas}
            className="mt-6"
        >
            {children}
        </GraphPanel>
    )
}
