import {
    Background,
    BackgroundVariant,
    ControlButton,
    Controls,
    ReactFlow,
    useReactFlow,
    type Edge,
    type Node,
    type NodeTypes,
    type XYPosition,
} from '@xyflow/react'
import { Maximize2, ZoomIn, ZoomOut } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'

import { fittedZoom, fitOptionsFor, MAX_ZOOM, MIN_ZOOM, steppedZoom, viewportSignature } from '@/lib/dag-layout'

/**
 * The canvas both graph screens draw on.
 *
 * A VIEW SELECTS AND NOTHING ELSE. Without `editing` a node is selectable and no more: not
 * draggable, not connectable, not deletable, and an edge is none of those either. That is the
 * run's graph, which draws what already happened.
 *
 * WITH `editing` THE CANVAS IS AN EDITOR. The pipeline editor hands it the five gestures a
 * document has an answer for -- draw an edge, delete one, move a box, finish moving it, drop a
 * connection on empty ground -- and every one of them ends in the same local document the step
 * pane and the source pane edit. Nothing is written here: this component reports the gesture and
 * the screen decides what it means.
 *
 * THE WHOLE GRAPH IS VISIBLE UNTIL SOMEBODY MOVES IT. A pipeline is a shape, and a reader
 * opening one is asking what shape it is -- so the view is fitted to every node, at a zoom held
 * between two bounds: a graph of two boxes sits modestly in the canvas rather than being blown
 * up to fill it, and a graph too big for the canvas is shown at a size its text can be read at
 * and panned to rather than shrunk past legibility. It is fitted again whenever the set of nodes
 * changes or the canvas is resized, and never again once the reader has panned, zoomed or dragged
 * a box: after that the view is theirs, and Re-layout is how they give it back.
 *
 * THE ZOOM CONTROLS ARE THIS APP'S. React Flow's own move by a fixed twenty percent, which on a
 * graph read at half size is four presses to nothing, and its fit button fits with the library's
 * options rather than the ones both canvases share.
 *
 * Everything the library paints is re-pointed at this app's tokens by `.dg-graph` in index.css,
 * so a graph is the same surfaces and the same hues as the table beside it.
 */

/** What a gesture on the canvas does, on a canvas that edits one. */
export interface CanvasEditing {
    /** An edge was drawn: `to` is to wait for `from`. */
    onConnect: (from: string, to: string) => void
    /** A chosen edge was deleted: `to` is to stop waiting for `from`. */
    onDisconnect: (from: string, to: string) => void
    /** A chosen node was deleted: the step goes, and so does every reference to it. */
    onRemove: (step: string) => void
    /** A box was right-clicked, at that point on the screen. */
    onNodeMenu: (step: string, at: { clientX: number; clientY: number }) => void
    /** Which edge is chosen, which is what a Delete takes away, or null when none is. */
    onChooseEdge: (id: string | null) => void
    /** A box is being dragged, in flow coordinates. */
    onMove: (id: string, at: XYPosition) => void
    /** The drag ended, which is when a position is worth keeping. */
    onMoveEnd: () => void
    /** A connection was let go over empty ground, at that point on the screen. */
    onDropped: (from: string, at: { clientX: number; clientY: number }) => void
}

/** The attribution corner is licensing chrome, not the graph's; MIT permits removing it. */
const PRO_OPTIONS = { hideAttribution: true }

export function GraphCanvas({
    nodes,
    edges,
    nodeTypes,
    editing = null,
    onSelect,
    control = null,
    children,
}: {
    nodes: Node[]
    edges: Edge[]
    nodeTypes: NodeTypes
    /** What a gesture changes, or nothing on a canvas that is a view. */
    editing?: CanvasEditing | null
    /** Called with the node chosen, or null when the ground under them was clicked. */
    onSelect: (id: string | null) => void
    /** One more button for the control cluster, above the zoom and fit this canvas always has. */
    control?: ReactNode
    /** What the canvas holds over the graph, such as an affordance in a corner. */
    children?: ReactNode
}) {
    // A pan, a zoom or a drag the reader made, which is what stops the canvas re-deciding the view.
    const [moved, setMoved] = useState(false)
    // A connection being drawn, which is what lights every port on the canvas at once.
    const [connecting, setConnecting] = useState(false)

    return (
        <ReactFlow
            proOptions={PRO_OPTIONS}
            className={`dg-graph${editing === null ? '' : ' dg-editable'}${connecting ? ' dg-connecting' : ''}`}
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={fitOptionsFor()}
            minZoom={MIN_ZOOM}
            maxZoom={MAX_ZOOM}
            nodesDraggable={editing !== null}
            nodesConnectable={editing !== null}
            edgesFocusable={editing !== null}
            elementsSelectable
            // React Flow answers neither key while the focus is in a text box, so a Backspace
            // meant for a config field is never a step.
            deleteKeyCode={editing === null ? null : ['Delete', 'Backspace']}
            onMoveStart={(event) => {
                // React Flow passes null for a move it made itself, so only a reader's own
                // gesture takes the view over.
                if (event !== null) setMoved(true)
            }}
            onNodeClick={(_, node) => {
                onSelect(node.id)
            }}
            onPaneClick={() => {
                onSelect(null)
            }}
            onNodeDragStart={() => {
                setMoved(true)
            }}
            onNodeContextMenu={
                editing === null
                    ? undefined
                    : (event, node) => {
                          event.preventDefault()
                          editing.onNodeMenu(node.id, { clientX: event.clientX, clientY: event.clientY })
                      }
            }
            onNodesDelete={
                editing === null
                    ? undefined
                    : (removed) => {
                          for (const node of removed) editing.onRemove(node.id)
                      }
            }
            onNodeDragStop={editing?.onMoveEnd}
            onNodesChange={
                editing === null
                    ? undefined
                    : (changes) => {
                          for (const change of changes) {
                              if (change.type === 'position' && change.position !== undefined) {
                                  editing.onMove(change.id, change.position)
                              }
                          }
                      }
            }
            onEdgesChange={
                editing === null
                    ? undefined
                    : (changes) => {
                          // One click arrives as the whole selection's changes at once -- the
                          // edge chosen and every edge unchosen -- so the batch decides, not
                          // whichever change happens to be last.
                          const selections = changes.filter((change) => change.type === 'select')
                          if (selections.length === 0) return
                          const chosen = selections.find((change) => change.selected)
                          editing.onChooseEdge(chosen?.id ?? null)
                      }
            }
            onEdgesDelete={
                editing === null
                    ? undefined
                    : (removed) => {
                          for (const edge of removed) editing.onDisconnect(edge.source, edge.target)
                      }
            }
            onConnectStart={() => {
                setConnecting(true)
            }}
            onConnect={(connection) => {
                editing?.onConnect(connection.source, connection.target)
            }}
            onConnectEnd={(event, state) => {
                setConnecting(false)
                const from = state.fromNode?.id
                if (editing === null || state.isValid === true || from === undefined) return
                // Let go over empty ground: the point is where the new step goes.
                const at = 'changedTouches' in event ? event.changedTouches[0] : event
                if (at === undefined) return
                editing.onDropped(from, { clientX: at.clientX, clientY: at.clientY })
            }}
        >
            <FitToGraph nodes={nodes} moved={moved} />
            <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
            <ZoomControls control={control} />
            {children}
        </ReactFlow>
    )
}

export const ZOOM_IN_LABEL = 'Zoom in'
export const ZOOM_OUT_LABEL = 'Zoom out'
export const FIT_VIEW_LABEL = 'Fit view'

/**
 * What the canvas offers in its corner: a zoom step worth pressing either way, the shared fit,
 * and whatever one control the screen adds above them.
 */
function ZoomControls({ control }: { control: ReactNode }) {
    const flow = useReactFlow()
    const step = (direction: 'in' | 'out') => () => {
        void flow.zoomTo(steppedZoom(flow.getZoom(), direction), { duration: 120 })
    }

    return (
        <Controls showZoom={false} showFitView={false} showInteractive={false}>
            {control}
            <ControlButton onClick={step('in')} title={ZOOM_IN_LABEL} aria-label={ZOOM_IN_LABEL}>
                <ZoomIn />
            </ControlButton>
            <ControlButton onClick={step('out')} title={ZOOM_OUT_LABEL} aria-label={ZOOM_OUT_LABEL}>
                <ZoomOut />
            </ControlButton>
            <ControlButton
                onClick={() => {
                    void fitCapped(flow)
                }}
                title={FIT_VIEW_LABEL}
                aria-label={FIT_VIEW_LABEL}
            >
                <Maximize2 />
            </ControlButton>
        </Controls>
    )
}

/**
 * Keeps the whole graph in view for as long as the reader has not taken the view over.
 *
 * IT IS A CHILD RATHER THAN THE CANVAS ITSELF because `useReactFlow` needs the instance, and
 * the instance exists only inside `ReactFlow`. `fitView` on the component alone is not enough:
 * a graph is placed by elk after the first render, so what that would fit is no nodes at all.
 */
function FitToGraph({ nodes, moved }: { nodes: Node[]; moved: boolean }) {
    const flow = useReactFlow()
    const wrapper = useRef<HTMLDivElement | null>(null)
    const signature = viewportSignature(nodes)

    useEffect(() => {
        if (moved || signature === '') return
        // One frame later: the nodes have to be measured before there is anything to fit to.
        const frame = requestAnimationFrame(() => {
            void fitCapped(flow)
        })
        return () => {
            cancelAnimationFrame(frame)
        }
    }, [flow, moved, signature])

    // The canvas gets narrower when the right panel is dragged open, and a graph that then
    // ran off under the panel is the shape no longer being readable.
    useEffect(() => {
        const element = wrapper.current?.parentElement
        if (element === null || element === undefined || moved) return
        const observer = new ResizeObserver(() => {
            void fitCapped(flow)
        })
        observer.observe(element)
        return () => {
            observer.disconnect()
        }
    }, [flow, moved])

    return <div ref={wrapper} className="hidden" aria-hidden />
}

/**
 * Fit the graph, then hold the zoom between the two bounds a fit is allowed.
 *
 * The bounds are applied after the fit as well as passed to it: a fit reads its own bounds from
 * the canvas, and neither a pipeline of two boxes magnified to fill it nor one of fifty shrunk
 * until its labels are grey lines is a reading of the shape.
 */
export async function fitCapped(flow: ReturnType<typeof useReactFlow>): Promise<void> {
    await flow.fitView(fitOptionsFor())
    const held = fittedZoom(flow.getZoom())
    if (held !== flow.getZoom()) await flow.zoomTo(held, { duration: 0 })
}
