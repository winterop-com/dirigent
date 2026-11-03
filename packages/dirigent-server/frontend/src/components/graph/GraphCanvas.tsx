import {
    Background,
    BackgroundVariant,
    ControlButton,
    Controls,
    ReactFlow,
    useReactFlow,
    useUpdateNodeInternals,
    type Edge,
    type EdgeTypes,
    type Node,
    type NodeTypes,
    type XYPosition,
} from '@xyflow/react'
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'

import { IconButton } from '@/components/ds/IconButton'
import { LayoutMenu } from '@/components/graph/LayoutMenu'
import { DirectionContext, RoutedEdge } from '@/components/graph/RoutedEdge'
import { useSmallScreen } from '@/hooks/use-small-screen'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { applePlatform, modifierLabel } from '@/lib/shortcuts'
import { cn } from '@/lib/utils'

import {
    DEFAULT_LAYOUT,
    fittedHeight,
    fittedZoom,
    fitOptionsFor,
    MAX_ZOOM,
    MIN_ZOOM,
    startOfOverflow,
    revealPoint,
    steppedZoom,
    viewMoved,
    viewportSignature,
    wheelZoomFactor,
    type CanvasView,
    type LayoutChoice,
} from '@/lib/dag-layout'

/**
 * The canvas every graph screen draws on.
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
 * WHERE IT STANDS DECIDES WHAT THE WHEEL DOES. A stage -- the editor's, or a graph opened in a
 * window -- takes the wheel and zooms on it, and so does a canvas filling the room its page leaves
 * it, which is the screen. A canvas sized to its drawing gives a plain wheel back to the page and
 * zooms on a pinch or on the platform's modifier held over the wheel. Every canvas pans when its
 * ground is dragged.
 *
 * THE WHOLE GRAPH IS VISIBLE UNTIL SOMEBODY MOVES IT. A pipeline is a shape, and a reader
 * opening one is asking what shape it is -- so the view is fitted to every node, at a zoom held
 * between two bounds. It is fitted again whenever the set of nodes changes, the canvas is resized
 * or the reader changes the layout, and never again once the reader has panned, zoomed or dragged
 * a box: after that the view is theirs, and the fit control is how they give it back.
 *
 * Everything the library paints is re-pointed at this app's tokens by `.dg-graph` in index.css,
 * so a graph is the same surfaces and the same hues as the table beside it.
 */

/** Where a canvas stands: a stage of its own, a window, or a page sized to its drawing or its room. */
export type CanvasFrame = 'stage' | 'window' | 'fitted' | 'filled'

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

/** A view on a page or in a window draws its edges as right-angled steps. */
const VIEW_EDGES = { type: 'smoothstep' as const }

/** The edge kinds a canvas draws beyond the library's own. Built once. */
const EDGE_TYPES: EdgeTypes = { routed: RoutedEdge }

export function GraphCanvas({
    nodes,
    edges,
    nodeTypes,
    editing = null,
    onSelect,
    control = null,
    frame = 'stage',
    layout = DEFAULT_LAYOUT,
    children,
}: {
    nodes: Node[]
    edges: Edge[]
    nodeTypes: NodeTypes
    /** What a gesture changes, or nothing on a canvas that is a view. */
    editing?: CanvasEditing | null
    /** Called with the node chosen, or null when the ground under them was clicked. */
    onSelect: (id: string | null) => void
    /** One more control for the cluster in a stage's corner, above the zoom and fit it always has. */
    control?: ReactNode
    /** What the canvas holds over the graph, such as an affordance in a corner. */
    children?: ReactNode
    frame?: CanvasFrame
    /** How the graph was laid out, which decides the side an edge meets a box and how it is drawn. */
    layout?: LayoutChoice
}) {
    const canvas = (
        <Canvas
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            editing={frame === 'stage' ? editing : null}
            onSelect={onSelect}
            control={control}
            frame={frame}
            layout={layout}
        >
            {children}
        </Canvas>
    )
    return (
        <DirectionContext value={layout.direction}>
            {frame === 'fitted' || frame === 'filled' ? (
                <PageBox nodes={nodes} filled={frame === 'filled'}>
                    {canvas}
                </PageBox>
            ) : (
                canvas
            )}
        </DirectionContext>
    )
}

/** The shortest a filled canvas is drawn, however little room the page leaves it. */
const FILLED_MIN_HEIGHT = 240

/**
 * The box a canvas on a page stands in. Fitted, its height follows the drawing at the width it has;
 * filled, it takes the room its page gives it -- down to the drawing's height or `FILLED_MIN_HEIGHT`,
 * whichever is less -- and a drawing taller than that is fitted at the floor and panned.
 */
function PageBox({ nodes, filled, children }: { nodes: Node[]; filled: boolean; children: ReactNode }) {
    const box = useRef<HTMLDivElement | null>(null)
    const [width, setWidth] = useState(0)
    useEffect(() => {
        const element = box.current
        if (element === null) return
        const observer = new ResizeObserver(() => {
            setWidth(element.clientWidth)
        })
        observer.observe(element)
        return () => {
            observer.disconnect()
        }
    }, [])
    const height = fittedHeight(boundsOf(nodes), width)
    return (
        <div
            ref={box}
            data-canvas-box={filled ? 'filled' : 'fitted'}
            className={cn('w-full', filled && 'flex-1')}
            style={filled ? { minHeight: Math.min(height, FILLED_MIN_HEIGHT) } : { height }}
        >
            {children}
        </div>
    )
}

/** The extent of a set of placed nodes, which is what a canvas on a page is sized to. */
function boundsOf(nodes: readonly Node[]): { width: number; height: number } {
    if (nodes.length === 0) return { width: 0, height: 0 }
    const left = Math.min(...nodes.map((node) => node.position.x))
    const top = Math.min(...nodes.map((node) => node.position.y))
    const right = Math.max(...nodes.map((node) => node.position.x + (node.width ?? 0)))
    const bottom = Math.max(...nodes.map((node) => node.position.y + (node.height ?? 0)))
    return { width: right - left, height: bottom - top }
}

/** A layout choice as one string, which is what a re-fit is keyed on. */
function layoutKey(layout: LayoutChoice): string {
    return `${layout.direction}/${layout.routing}/${layout.spacing}`
}

function Canvas({
    nodes,
    edges,
    nodeTypes,
    editing,
    onSelect,
    control = null,
    frame,
    layout,
    children,
}: {
    nodes: Node[]
    edges: Edge[]
    nodeTypes: NodeTypes
    editing: CanvasEditing | null
    onSelect: (id: string | null) => void
    control?: ReactNode
    frame: CanvasFrame
    layout: LayoutChoice
    children?: ReactNode
}) {
    // A pan, a zoom or a drag the reader made, which is what stops the canvas re-deciding the view.
    const [moved, setMoved] = useState(false)
    // A new layout is a new drawing, and the view is fitted to it again.
    const key = layoutKey(layout)
    const [laidOut, setLaidOut] = useState(key)
    if (laidOut !== key) {
        setLaidOut(key)
        setMoved(false)
    }
    // Where the view stood when the reader's current pan or zoom began.
    const gesture = useRef<CanvasView | null>(null)
    // A connection being drawn, which is what lights every port on the canvas at once.
    const [connecting, setConnecting] = useState(false)

    const onPage = frame === 'fitted' || frame === 'filled'
    const small = useSmallScreen()

    const drawn = useMemo<Edge[]>(() => {
        if (layout.routing === 'default') return edges
        const curved = layout.routing === 'splines'
        return edges.map((edge) => ({ ...edge, type: 'routed', data: { ...edge.data, curved } }))
    }, [edges, layout.routing])

    return (
        <ReactFlow
            proOptions={PRO_OPTIONS}
            className={cn(
                'dg-graph',
                editing !== null && 'dg-editable',
                connecting && 'dg-connecting',
                onPage && 'dg-fitted',
            )}
            // A finger on a phone scrolls the page; the graph's window is where it is panned.
            panOnDrag={!(onPage && small)}
            zoomOnScroll={!onPage}
            zoomOnPinch
            zoomOnDoubleClick={!onPage}
            preventScrolling={!onPage}
            nodes={nodes}
            edges={drawn}
            edgeTypes={EDGE_TYPES}
            defaultEdgeOptions={frame === 'stage' ? undefined : VIEW_EDGES}
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
            onMoveStart={(event, view) => {
                // React Flow passes null for a move it made itself, so only a reader's own
                // gesture can take the view over.
                gesture.current = event === null ? null : view
            }}
            onMoveEnd={(event, view) => {
                const from = gesture.current
                gesture.current = null
                if (event !== null && from !== null && viewMoved(from, view)) setMoved(true)
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
            <FitToGraph nodes={nodes} moved={moved} direction={layout.direction} />
            {onPage && (
                <PageWheel
                    plain={frame === 'filled'}
                    onZoomed={() => {
                        setMoved(true)
                    }}
                />
            )}
            {!onPage && <Background variant={BackgroundVariant.Dots} gap={18} size={1} />}
            {!onPage && <ZoomControls control={control} empty={nodes.length === 0} />}
            {children}
        </ReactFlow>
    )
}

export const ZOOM_IN_LABEL = LABELS.shell.zoom_in
export const ZOOM_OUT_LABEL = LABELS.shell.zoom_out
export const FIT_VIEW_LABEL = LABELS.shell.fit_view
export const LAYOUT_LABEL = LABELS.shell.layout.menu

/**
 * What a stage offers in its corner: a zoom step worth pressing either way, the shared fit, and
 * whatever one control the screen adds above them. A canvas with nothing on it has nothing to
 * zoom, so it offers the screen's control alone.
 */
function ZoomControls({ control, empty }: { control: ReactNode; empty: boolean }) {
    const flow = useReactFlow()
    const step = (direction: 'in' | 'out') => () => {
        void flow.zoomTo(steppedZoom(flow.getZoom(), direction), { duration: 120 })
    }

    return (
        <Controls showZoom={false} showFitView={false} showInteractive={false}>
            {control}
            {!empty && (
                <>
                    <ControlButton onClick={step('in')} title={ZOOM_IN_LABEL} aria-label={ZOOM_IN_LABEL}>
                        <ICONS.zoom_in />
                    </ControlButton>
                    <ControlButton onClick={step('out')} title={ZOOM_OUT_LABEL} aria-label={ZOOM_OUT_LABEL}>
                        <ICONS.zoom_out />
                    </ControlButton>
                    <ControlButton
                        onClick={() => {
                            void fitCapped(flow)
                        }}
                        title={FIT_VIEW_LABEL}
                        aria-label={FIT_VIEW_LABEL}
                    >
                        <ICONS.fit_view />
                    </ControlButton>
                </>
            )}
        </Controls>
    )
}

/** The layout control a stage carries in its corner, among the zoom controls. */
export function LayoutControl({
    layout,
    onLayout,
}: {
    layout: LayoutChoice
    onLayout: (layout: LayoutChoice) => void
}) {
    return (
        <LayoutMenu
            choice={layout}
            onChoose={onLayout}
            trigger={
                <ControlButton title={LAYOUT_LABEL} aria-label={LAYOUT_LABEL}>
                    <ICONS.graph_layout />
                </ControlButton>
            }
        />
    )
}

/**
 * What a canvas on a page offers in its panel's bar rather than over its drawing: the two zoom
 * steps, which say how else the canvas zooms, the shared fit, and the layout.
 *
 * It reads the canvas through the provider the page wraps both in.
 */
export function PageCanvasTools({
    frame,
    layout,
    onLayout,
}: {
    frame: Extract<CanvasFrame, 'fitted' | 'filled'>
    layout: LayoutChoice
    onLayout: (layout: LayoutChoice) => void
}) {
    const flow = useReactFlow()
    const modifier = modifierLabel(applePlatform(navigator.userAgent))
    const filled = frame === 'filled'
    const step = (direction: 'in' | 'out') => () => {
        void flow.zoomTo(steppedZoom(flow.getZoom(), direction), { duration: 120 })
    }
    return (
        <span className="flex items-center gap-0.5 font-normal">
            <IconButton
                icon={ICONS.zoom_out}
                label={ZOOM_OUT_LABEL}
                tooltip={filled ? LABELS.shell.zoom_out_filled : LABELS.shell.zoom_out_on_page(modifier)}
                size="sm"
                className="text-muted-foreground"
                onClick={step('out')}
            />
            <IconButton
                icon={ICONS.zoom_in}
                label={ZOOM_IN_LABEL}
                tooltip={filled ? LABELS.shell.zoom_in_filled : LABELS.shell.zoom_in_on_page(modifier)}
                size="sm"
                className="text-muted-foreground"
                onClick={step('in')}
            />
            <IconButton
                icon={ICONS.fit_view}
                label={FIT_VIEW_LABEL}
                size="sm"
                className="text-muted-foreground"
                onClick={() => {
                    void fitCapped(flow)
                }}
            />
            <LayoutMenu
                choice={layout}
                onChoose={onLayout}
                trigger={
                    <IconButton
                        icon={ICONS.graph_layout}
                        label={LAYOUT_LABEL}
                        size="sm"
                        className="text-muted-foreground"
                    />
                }
            />
        </span>
    )
}

/**
 * A wheel over a canvas on a page zooms it with Ctrl or the platform's modifier held, or as a
 * trackpad pinch, which browsers send as a wheel with Ctrl. With `plain`, every wheel zooms it and
 * none reaches the page; without, every other wheel scrolls the page.
 *
 * The zoom is anchored on the pointer and moves by `wheelZoomFactor` per event, so a pinch's run
 * of small deltas and a mouse wheel's notches both zoom at a pace that can be followed.
 */
function PageWheel({ plain, onZoomed }: { plain: boolean; onZoomed: () => void }) {
    const flow = useReactFlow()
    const marker = useRef<HTMLDivElement | null>(null)
    const zoomed = useRef(onZoomed)
    useEffect(() => {
        zoomed.current = onZoomed
    }, [onZoomed])
    useEffect(() => {
        const element = marker.current?.closest('.react-flow')
        if (!(element instanceof HTMLElement)) return
        const onWheel = (event: WheelEvent) => {
            if (!plain && !event.ctrlKey && !event.metaKey) return
            event.preventDefault()
            event.stopPropagation()
            const view = flow.getViewport()
            const zoom = Math.min(
                MAX_ZOOM,
                Math.max(MIN_ZOOM, view.zoom * wheelZoomFactor(event.deltaY, event.deltaMode)),
            )
            if (zoom === view.zoom) return
            const box = element.getBoundingClientRect()
            const at = { x: event.clientX - box.left, y: event.clientY - box.top }
            void flow.setViewport(
                {
                    x: at.x - ((at.x - view.x) * zoom) / view.zoom,
                    y: at.y - ((at.y - view.y) * zoom) / view.zoom,
                    zoom,
                },
                { duration: 0 },
            )
            zoomed.current()
        }
        element.addEventListener('wheel', onWheel, { capture: true, passive: false })
        return () => {
            element.removeEventListener('wheel', onWheel, { capture: true })
        }
    }, [flow, plain])
    return <div ref={marker} className="hidden" aria-hidden />
}

/**
 * Keeps the whole graph in view for as long as the reader has not taken the view over.
 *
 * IT IS A CHILD RATHER THAN THE CANVAS ITSELF because `useReactFlow` needs the instance, and
 * the instance exists only inside `ReactFlow`. `fitView` on the component alone is not enough:
 * a graph is placed by elk after the first render, so what that would fit is no nodes at all.
 */
function FitToGraph({ nodes, moved, direction }: { nodes: Node[]; moved: boolean; direction: string }) {
    const flow = useReactFlow()
    const updateInternals = useUpdateNodeInternals()
    const wrapper = useRef<HTMLDivElement | null>(null)
    const signature = viewportSignature(nodes)

    // A box's anchors move to other sides when the direction changes, and the library reads
    // where they are only when it is told to.
    const ids = useRef<string[]>([])
    useEffect(() => {
        ids.current = nodes.map((node) => node.id)
    }, [nodes])
    const anchored = useRef(direction)
    useEffect(() => {
        if (anchored.current === direction) return
        anchored.current = direction
        const frame = requestAnimationFrame(() => {
            updateInternals(ids.current)
        })
        return () => {
            cancelAnimationFrame(frame)
        }
    }, [direction, updateInternals])

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

    const chosen = nodes.find((node) => node.selected === true)?.id ?? null
    const selected = useRef(chosen)
    useEffect(() => {
        selected.current = chosen
    }, [chosen])

    // The canvas gets narrower when the right panel opens, and a graph that then ran off under
    // the panel is the shape no longer being readable. A view the reader has taken over is not
    // re-fitted; only the chosen box is brought back onto the canvas if the resize cut it.
    useEffect(() => {
        const element = wrapper.current?.parentElement
        if (element === null || element === undefined) return
        const observer = new ResizeObserver(() => {
            if (!moved) {
                void fitCapped(flow)
                return
            }
            const node = selected.current === null ? undefined : flow.getInternalNode(selected.current)
            if (node === undefined) return
            const box = {
                ...node.internals.positionAbsolute,
                width: node.measured.width ?? 0,
                height: node.measured.height ?? 0,
            }
            const view = flow.getViewport()
            const centre = revealPoint(box, view, {
                width: element.clientWidth,
                height: element.clientHeight,
            })
            if (centre !== null) void flow.setCenter(centre.x, centre.y, { zoom: view.zoom, duration: 0 })
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
 * until its labels are grey lines is a reading of the shape. What does not fit at the floor hangs
 * off the far edges, with the graph's start on the canvas.
 */
export async function fitCapped(flow: ReturnType<typeof useReactFlow>): Promise<void> {
    await flow.fitView(fitOptionsFor())
    const held = fittedZoom(flow.getZoom())
    if (held !== flow.getZoom()) await flow.zoomTo(held, { duration: 0 })
    const view = flow.getViewport()
    const placed = startOfOverflow(view, flow.getNodesBounds(flow.getNodes()))
    if (placed.x !== view.x || placed.y !== view.y) await flow.setViewport(placed, { duration: 0 })
}
