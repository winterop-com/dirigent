import { ReactFlowProvider, useReactFlow, type Edge } from '@xyflow/react'
import { useEffect, useMemo, useState, type MouseEvent } from 'react'

import { fitCapped, GraphCanvas, type CanvasEditing } from '@/components/graph/GraphCanvas'
import { usePlacedGraph } from '@/components/graph/use-placed'
import { AddStepButton, AddStepMenuAt } from '@/components/pipeline/AddStepMenu'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { addStepAsked, relayoutAsked } from '@/lib/canvas-actions'
import { StepNode, type DocumentNode } from '@/components/pipeline/StepNode'
import { useStore } from '@/hooks/use-store'
import type { JsonMap } from '@/lib/api'
import type { BlockEntry } from '@/lib/blocks'
import {
    forgetPlacements,
    heldLayout,
    holdPlacement,
    keepPlacements,
    loadPlacements,
    withHeld,
    type Placement,
    type Placements,
} from '@/lib/canvas-layout'
import { DOCUMENT_NODE_HEIGHT, drawnSize, NODE_WIDTH, RANK_SPACING, type LayoutShape } from '@/lib/dag-layout'
import {
    blockOf,
    edgesIn,
    fanOutOf,
    stepEdited,
    stepHeading,
    stepNames,
    type DocumentEdits,
} from '@/lib/pipeline-document'
import { stepMissing, type Unmet } from '@/lib/requirements'

/**
 * The document's graph: the steps it declares and the edges its `depends_on` draws.
 *
 * THIS IS THE DOCUMENT, NOT A RUN. It is the current version's steps as edited here, so a step
 * added in the panel appears the moment it is added and wears the mark saying it is unapplied.
 *
 * THE CANVAS EDITS. An edge dragged between two ports is a `depends_on` entry, the same one the
 * chips in the step's pane add and remove, and a selected edge deleted with the key takes it
 * away again. A connection let go over empty ground opens the add-step menu already waiting for
 * the step it came from. None of it is written to the instance: every gesture ends in the local
 * document, and the topbar counts it with every other unapplied edit.
 *
 * THE GROUND IS WHERE A STEP IS ADDED. A right-click on empty canvas opens the add-step menu at
 * the pointer, and the button in the corner opens the same menu under itself. A right-click on a
 * box opens that box's own menu instead: one more step after this one, which is the add-step menu
 * again with the edge already decided, and this one taken out.
 *
 * A CHOSEN STEP IS DELETED BY THE KEY, the way a chosen edge is. It takes its own edges with it:
 * a `depends_on` naming a step the document no longer has is what an apply refuses.
 *
 * ELK DECIDES WHERE A BOX GOES UNTIL SOMEBODY MOVES IT. A dragged position is that pipeline's,
 * kept in `lib/canvas-layout` and surviving a reload; Re-layout gives the whole arrangement back
 * to elk and fits the view to it again.
 *
 * This module is loaded lazily. React Flow and elk are shared with the run graph and neither is
 * in the entry chunk.
 */

/** The one node kind this graph draws. Built once: React Flow re-mounts every node on a new object. */
const NODE_TYPES = { step: StepNode }

export const RELAYOUT_LABEL = 'Re-layout'

export const ADD_AFTER_LABEL = 'Add step after'
export const DELETE_STEP_LABEL = 'Delete step'

/** What another pipeline's arrangement amounts to here: nothing, and the same nothing each time. */
const NO_PLACEMENTS: Placements = {}

export interface PipelineGraphProps {
    /** The pipeline being edited, which is what an arrangement is kept under. */
    pipeline: string
    document: JsonMap
    /** The catalog this instance answered with, which is what the add-step menu offers. */
    blocks: BlockEntry[]
    edits: DocumentEdits
    /** What this instance has not got of what the document names. */
    unmet: Unmet
    selected: string | null
    onSelect: (step: string | null) => void
    /** A block was chosen, from the pointer or from the button: a step runs it. */
    onAddStep: (block: string) => void
    /** An edge was drawn: `to` is to wait for `from`. */
    onConnect: (from: string, to: string) => void
    /** An edge was deleted: `to` is to stop waiting for `from`. */
    onDisconnect: (from: string, to: string) => void
    /** A block was chosen after a connection was dropped on empty ground, at that point in
     * flow coordinates: the step runs it, waits for `from`, and stays where it was dropped. */
    onAddStepAfter: (from: string, block: string, at: Placement) => void
    /** A step was deleted: it goes, and so does every reference to it. */
    onRemoveStep: (step: string) => void
    /**
     * Draw the document rather than edit it.
     *
     * The canvas keeps its ports as anchors and shows none, the add-step control and both
     * menus are not drawn, and a step is chosen and nothing else -- which is what the run's
     * own graph has always been.
     */
    readOnly?: boolean
}

/**
 * The provider is this component's own, so what is inside it can ask the canvas where a point on
 * the screen is on the graph. React Flow uses one that already exists rather than making a
 * second.
 */
export function PipelineGraph(props: PipelineGraphProps) {
    return (
        <ReactFlowProvider>
            <EditableGraph {...props} />
        </ReactFlowProvider>
    )
}

function EditableGraph({
    pipeline,
    document,
    blocks,
    edits,
    unmet,
    selected,
    onSelect,
    onAddStep,
    onConnect,
    onDisconnect,
    onAddStepAfter,
    onRemoveStep,
    readOnly = false,
}: PipelineGraphProps) {
    const flow = useReactFlow()
    const layout = useStore(heldLayout)
    const [chosenEdge, setChosenEdge] = useState<string | null>(null)
    // Where the pointer opened the menu, in viewport coordinates, or null while it is shut.
    const [pointer, setPointer] = useState<{ x: number; y: number } | null>(null)
    // A connection let go over empty ground: what it was drawn from, where the menu opens, and
    // where in the graph the step it adds is drawn.
    const [dropped, setDropped] = useState<{
        from: string
        at: Placement
        over: { x: number; y: number }
    } | null>(null)
    // A box that was right-clicked: which step, and where its menu opens.
    const [onNode, setOnNode] = useState<{ step: string; over: { x: number; y: number } } | null>(null)

    useEffect(() => {
        loadPlacements(pipeline)
    }, [pipeline])

    // The palette's asks: the menu opens over the canvas's middle, since the palette is a
    // keyboard gesture with no place on the screen to hang off.
    const asked = useStore(addStepAsked)
    useEffect(() => {
        if (asked === 0) return
        const host = globalThis.document.querySelector('[data-canvas-host]')
        if (host === null) return
        const box = host.getBoundingClientRect()
        // The palette's ask is the external event this synchronizes with; the menu opens once
        // per bump, over the canvas's middle.
        // oxlint-disable-next-line react/set-state-in-effect
        setPointer({ x: box.x + box.width / 2, y: box.y + box.height / 3 })
    }, [asked])
    const tidy = useStore(relayoutAsked)
    useEffect(() => {
        if (tidy === 0) return
        forgetPlacements()
        void fitCapped(flow)
    }, [tidy, flow])

    const shape = useMemo<LayoutShape>(
        () => ({
            nodes: stepNames(document).map((name) => ({ id: name, height: DOCUMENT_NODE_HEIGHT })),
            edges: edgesIn(document),
        }),
        [document],
    )
    const placed = usePlacedGraph(shape)

    // An arrangement is one pipeline's, so another pipeline's is nothing until its own is read.
    const placements = layout.pipeline === pipeline ? layout.placements : NO_PLACEMENTS

    const nodes = useMemo<DocumentNode[]>(() => {
        if (placed === null) return []
        return withHeld(placed.nodes, placements).map((node) => {
            const fan = fanOutOf(document, node.id)
            return {
                id: node.id,
                type: 'step' as const,
                position: { x: node.x, y: node.y },
                width: node.width,
                height: node.height,
                measured: drawnSize(node),
                selected: node.id === selected,
                data: {
                    ...stepHeading(document, node.id),
                    block: blockOf(document, node.id) ?? 'no block',
                    edited: stepEdited(edits, node.id),
                    missing: stepMissing(unmet, node.id),
                    fanOut: fan.fanOut,
                    fanOutItems: fan.items,
                    editable: true,
                },
            }
        })
    }, [document, edits, placed, placements, selected, unmet])

    const edges = useMemo<Edge[]>(() => {
        if (placed === null) return []
        return placed.edges.map((edge) => ({
            id: edge.id,
            source: edge.source,
            target: edge.target,
            selected: edge.id === chosenEdge,
        }))
    }, [chosenEdge, placed])

    const editing = useMemo<CanvasEditing>(
        () => ({
            onConnect,
            onDisconnect,
            // ONE THING IS CHOSEN AT A TIME. A key deletes what is chosen, and a canvas holding
            // both a step and an edge chosen would answer one press by taking away two.
            onChooseEdge: (id) => {
                setChosenEdge(id)
                if (id !== null) onSelect(null)
            },
            onMove: (id, at) => {
                holdPlacement(id, at)
            },
            onMoveEnd: keepPlacements,
            onDropped: (from, at) => {
                setDropped({
                    from,
                    at: flow.screenToFlowPosition({ x: at.clientX, y: at.clientY }),
                    over: { x: at.clientX, y: at.clientY },
                })
            },
            onRemove: onRemoveStep,
            onNodeMenu: (step, at) => {
                setPointer(null)
                setDropped(null)
                setOnNode({ step, over: { x: at.clientX, y: at.clientY } })
            },
        }),
        [flow, onConnect, onDisconnect, onRemoveStep, onSelect],
    )

    const choose = (id: string | null) => {
        setChosenEdge(null)
        onSelect(id)
    }

    // A box answers with its own menu, so the ground is what this one answers for.
    const onContextMenu = (event: MouseEvent<HTMLDivElement>) => {
        if (readOnly) return
        if (event.target instanceof Element && event.target.closest('.react-flow__node') !== null) return
        event.preventDefault()
        setDropped(null)
        setOnNode(null)
        setPointer({ x: event.clientX, y: event.clientY })
    }

    return (
        <div className="absolute inset-0" data-canvas-host onContextMenu={onContextMenu}>
            <GraphCanvas
                nodes={nodes}
                edges={edges}
                nodeTypes={NODE_TYPES}
                editing={readOnly ? undefined : editing}
                onSelect={choose}
                control={readOnly ? undefined : <AddStepButton blocks={blocks} onChoose={onAddStep} />}
            />

            {pointer !== null && (
                <AddStepMenuAt
                    blocks={blocks}
                    at={pointer}
                    onChoose={onAddStep}
                    onClose={() => {
                        setPointer(null)
                    }}
                />
            )}

            {onNode !== null && (
                <StepMenuAt
                    step={onNode.step}
                    at={onNode.over}
                    onAddAfter={() => {
                        const box = flow.getNode(onNode.step)
                        setOnNode(null)
                        if (box === undefined) return
                        setDropped({
                            from: onNode.step,
                            at: { x: box.position.x + NODE_WIDTH + RANK_SPACING, y: box.position.y },
                            over: onNode.over,
                        })
                    }}
                    onRemove={() => {
                        setOnNode(null)
                        onRemoveStep(onNode.step)
                    }}
                    onClose={() => {
                        setOnNode(null)
                    }}
                />
            )}

            {dropped !== null && (
                <AddStepMenuAt
                    blocks={blocks}
                    at={dropped.over}
                    after={dropped.from}
                    onChoose={(block) => {
                        onAddStepAfter(dropped.from, block, dropped.at)
                    }}
                    onClose={() => {
                        setDropped(null)
                    }}
                />
            )}
        </div>
    )
}

/**
 * A box's own menu: what a step on this canvas can be asked for.
 *
 * The anchor is an element of no size at the pointer, the way the add-step menu's is, so the
 * popup stays inside the viewport rather than being placed by hand.
 */
function StepMenuAt({
    step,
    at,
    onAddAfter,
    onRemove,
    onClose,
}: {
    step: string
    at: { x: number; y: number }
    onAddAfter: () => void
    onRemove: () => void
    onClose: () => void
}) {
    return (
        <DropdownMenu
            open
            onOpenChange={(next) => {
                if (!next) onClose()
            }}
        >
            <DropdownMenuTrigger
                aria-label={step}
                tabIndex={-1}
                className="pointer-events-none fixed size-0"
                style={{ left: at.x, top: at.y }}
            />
            <DropdownMenuContent align="start" className="w-56">
                <p className="truncate px-2 py-1.5 font-mono text-xs text-faint">{step}</p>
                <DropdownMenuItem onClick={onAddAfter}>{ADD_AFTER_LABEL}</DropdownMenuItem>
                <DropdownMenuItem className="destructive-action" onClick={onRemove}>
                    {DELETE_STEP_LABEL}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
