/**
 * Placing a DAG, left to right.
 *
 * A graph off the wire has nodes and edges and no geometry, and React Flow draws what it is
 * given rather than deciding where anything goes. elk's layered algorithm is what decides, and
 * this module is the whole of the conversation with it: a shape in, positioned nodes and edges
 * out.
 *
 * IT KNOWS NOTHING ABOUT RUNS OR DOCUMENTS. A run's graph is its pinned definition with a state
 * on each node; a pipeline editor's graph is the stored document with an edit mark on each. The
 * geometry of the two is the same problem, so what elk is handed is an id and a height per node
 * and a pair per edge, and each screen reduces its own shape to that.
 *
 * THE ELK CALL IS INJECTED. Layout is asynchronous and elk is a large bundle that a test has no
 * business loading, so the two pure halves -- what is sent and what is read back -- are their
 * own functions and the engine is a parameter. `layoutDag` is what a component calls.
 *
 * A NODE IS A FIXED SIZE. A box is never stretched -- the editor's canvas moves one and the run's
 * moves nothing -- so a node's size is a property of what it holds rather than of the pointer.
 * Elk is told the size up front, which is what lets it route edges that do not cross the boxes.
 *
 * WHAT ELK DECIDES IS WHERE A BOX STARTS. A position somebody dragged it to is `lib/canvas-layout`
 * and is applied over this, so a step nobody has moved keeps the suggestion made here.
 *
 * A DEEP GRAPH IS WRAPPED ONTO ROWS RATHER THAN DRAWN AS ONE. Seventeen steps in one left-to-right
 * row is three thousand pixels of canvas, and fitting that to a laptop puts a node's text under
 * six pixels. Past `WRAP_WIDTH` elk is asked to cut the layering into chunks stacked down the
 * canvas: the ranks still read left to right, and the height nothing was using carries the rest.
 */

/** How wide every node is drawn. */
export const NODE_WIDTH = 200

/** How tall an ordinary node is: three lines and its padding. */
export const NODE_HEIGHT = 76

/** What a fan-out node's item strip adds to its height. */
export const STRIP_HEIGHT = 26

/** One line of a node's text, which is what a box loses when it stops carrying one. */
export const LINE_HEIGHT = 18

/** What a box that carries no third line saves at the foot of it, where nothing is drawn. */
export const TIGHT_PADDING = 4

/** One node to place: what it is called, and how tall it will be drawn. */
export interface LayoutNode {
    id: string
    height: number
}

/** What a screen reduces its own graph to before elk sees it. */
export interface LayoutShape {
    nodes: LayoutNode[]
    /** `[from, to]` pairs, pointing from prerequisite to dependent. */
    edges: [string, string][]
}

/** The subset of elk's graph shape this module builds. */
export interface ElkGraph {
    id: string
    layoutOptions: Record<string, string>
    children: { id: string; width: number; height: number }[]
    edges: { id: string; sources: string[]; targets: string[] }[]
}

/** The subset of elk's answer this module reads. */
export interface ElkLaidOut {
    children?: { id: string; x?: number; y?: number; width?: number; height?: number }[]
}

/** What `layoutDag` needs an elk to be. */
export interface ElkEngine {
    layout: (graph: ElkGraph) => Promise<ElkLaidOut>
}

/** One node, placed. */
export interface PlacedNode {
    id: string
    x: number
    y: number
    width: number
    height: number
}

/** One edge, named by the pair it joins. */
export interface PlacedEdge {
    id: string
    source: string
    target: string
}

/** A whole graph, placed. */
export interface PlacedGraph {
    nodes: PlacedNode[]
    edges: PlacedEdge[]
}

/** How much canvas one rank takes: a node and the gap to the next rank. */
export const RANK_SPACING = 44

/** How far apart two nodes of one rank sit. */
export const NODE_SPACING = 20

/**
 * The layout elk is asked for: layered, left to right, ordered as the API listed the nodes.
 *
 * `NODE_PLACEMENT` is elk's network simplex, which is what keeps a long chain on one row
 * instead of stepping it diagonally down the canvas.
 */
export const LAYOUT_OPTIONS: Record<string, string> = {
    'elk.algorithm': 'layered',
    'elk.direction': 'RIGHT',
    'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
    'elk.layered.spacing.nodeNodeBetweenLayers': String(RANK_SPACING),
    'elk.spacing.nodeNode': String(NODE_SPACING),
    'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES',
    'elk.edgeRouting': 'POLYLINE',
}

/**
 * How wide a graph may be drawn before its ranks are wrapped onto rows.
 *
 * It is about what a canvas can show at `FIT_MIN_ZOOM` with the fit's own padding around it, so
 * a graph is wrapped when drawing it in one row would put its text below a size worth reading.
 */
export const WRAP_WIDTH = 1400

/**
 * What elk is told when a graph is too wide to draw in one row: cut the layering into chunks
 * and stack them, aiming at a shape wider than it is tall, the way a canvas is.
 */
export const WRAP_OPTIONS: Record<string, string> = {
    'elk.layered.wrapping.strategy': 'MULTI_EDGE',
    'elk.aspectRatio': '2.0',
    'elk.layered.wrapping.additionalEdgeSpacing': '24',
}

/**
 * How many ranks deep a shape is: the longest chain of dependencies in it.
 *
 * The walk carries the nodes already on the path, so a shape that has somehow closed a loop --
 * which an apply refuses and the canvas refuses before that -- is measured rather than hung on.
 */
export function rankDepth(shape: LayoutShape): number {
    const after = new Map<string, string[]>()
    for (const [from, to] of shape.edges) after.set(from, [...(after.get(from) ?? []), to])

    const depths = new Map<string, number>()
    const depthFrom = (id: string, path: ReadonlySet<string>): number => {
        const held = depths.get(id)
        if (held !== undefined) return held
        if (path.has(id)) return 1
        const onward = new Set([...path, id])
        const deepest = (after.get(id) ?? []).reduce((most, next) => Math.max(most, depthFrom(next, onward)), 0)
        const depth = deepest + 1
        depths.set(id, depth)
        return depth
    }

    return shape.nodes.reduce((most, node) => Math.max(most, depthFrom(node.id, new Set())), 0)
}

/** How wide a shape would be drawn in one left-to-right row. */
export function unwrappedWidth(shape: LayoutShape): number {
    const ranks = rankDepth(shape)
    return ranks === 0 ? 0 : ranks * NODE_WIDTH + (ranks - 1) * RANK_SPACING
}

/** The options one shape is placed with: the layered ones, plus wrapping when it is too wide. */
export function layoutOptionsFor(shape: LayoutShape): Record<string, string> {
    return unwrappedWidth(shape) > WRAP_WIDTH ? { ...LAYOUT_OPTIONS, ...WRAP_OPTIONS } : LAYOUT_OPTIONS
}

/** How tall one node is drawn, which depends on whether it carries an item strip. */
export function heightOf(fanOut: boolean): number {
    return fanOut ? NODE_HEIGHT + STRIP_HEIGHT : NODE_HEIGHT
}

/**
 * How tall a node on the editor's canvas is.
 *
 * Shorter than a run's, because a run's third line is live state -- what a step is waiting for,
 * how a retry went, how long it took -- and a document has no state to say. Its foot is tighter
 * as well: with nothing under the second line, the room a run's box keeps for a strip is room
 * this one is only padding with. Elk is told the height the box is actually drawn at or the rows
 * come out spaced for a box that is not there.
 */
export const DOCUMENT_NODE_HEIGHT = NODE_HEIGHT - LINE_HEIGHT - TIGHT_PADDING

/**
 * What decides the geometry: which nodes there are, how tall each is, and what joins them.
 *
 * A graph is re-placed when this string changes and not when anything else does, so a step
 * going from running to succeeded, or a config field being typed into, moves no box.
 */
export function signatureOf(shape: LayoutShape): string {
    return [
        shape.nodes.map((node) => `${node.id}:${String(node.height)}`).join(','),
        shape.edges.map(([from, to]) => `${from}>${to}`).join(','),
    ].join('|')
}

/** The graph elk is handed: one child per node, one edge per dependency. */
export function toElkGraph(shape: LayoutShape): ElkGraph {
    const known = new Set(shape.nodes.map((node) => node.id))
    return {
        id: 'dag',
        layoutOptions: layoutOptionsFor(shape),
        children: shape.nodes.map((node) => ({ id: node.id, width: NODE_WIDTH, height: node.height })),
        // An edge to or from a node the shape does not carry would be an edge elk cannot place.
        edges: shape.edges
            .filter(([from, to]) => known.has(from) && known.has(to))
            .map(([from, to]) => ({ id: `${from}->${to}`, sources: [from], targets: [to] })),
    }
}

/**
 * Read elk's answer back as positions.
 *
 * A child elk placed nowhere is placed at the origin rather than dropped: a node missing from
 * the graph is a step missing from the screen, which is worse than one drawn in the wrong place.
 */
export function fromElkGraph(shape: LayoutShape, laid: ElkLaidOut): PlacedGraph {
    const placed = new Map((laid.children ?? []).map((child) => [child.id, child]))
    const known = new Set(shape.nodes.map((node) => node.id))
    return {
        nodes: shape.nodes.map((node) => {
            const child = placed.get(node.id)
            return {
                id: node.id,
                x: child?.x ?? 0,
                y: child?.y ?? 0,
                width: child?.width ?? NODE_WIDTH,
                height: child?.height ?? node.height,
            }
        }),
        edges: shape.edges
            .filter(([from, to]) => known.has(from) && known.has(to))
            .map(([from, to]) => ({ id: `${from}->${to}`, source: from, target: to })),
    }
}

/** Place a graph. */
export async function layoutDag(shape: LayoutShape, elk: ElkEngine): Promise<PlacedGraph> {
    if (shape.nodes.length === 0) return { nodes: [], edges: [] }
    return fromElkGraph(shape, await elk.layout(toElkGraph(shape)))
}

/**
 * The size a placed node is drawn at, as React Flow's own measurement of it.
 *
 * THIS IS WHAT KEEPS THE EDGES ON THE CANVAS. React Flow throws away the handle bounds of every
 * node object it has not seen before unless the node states its own measurement, and it draws no
 * edge at all to a node whose bounds it does not have. A canvas rebuilds its node objects
 * whenever what they say changes -- on a live run that is every frame the stream delivers and
 * every second a retry counts down -- so without this the graph loses its edges over and over,
 * and gets them back only once each box has been measured again.
 *
 * The size is the truth rather than a claim: React Flow writes a node's width and height as the
 * element's own style, so a box is exactly the size elk was told.
 */
export function drawnSize(node: PlacedNode): { width: number; height: number } {
    return { width: node.width, height: node.height }
}

/**
 * How much room is left around a fitted graph, as a fraction of the canvas.
 *
 * Enough that a node at the edge is not touching it, and no more: the padding is space the
 * shape is not being drawn in.
 */
export const FIT_PADDING = 0.14

/**
 * How far a fit is allowed to zoom in.
 *
 * A GRAPH OF TWO BOXES MUST NOT BE BLOWN UP TO FILL THE CANVAS, AND MUST NOT BE LOST IN IT
 * EITHER. Fitting a small shape to a large space magnifies it until a step is the size of a
 * card, which says the pipeline is bigger than it is; fitting it at its own size leaves a
 * single step as a small box adrift in the dotted ground. A quarter over its own size is the
 * middle of those two: a one-step run opens at a size worth reading, and a fifty-step one is
 * still zoomed out until all of it is on screen.
 */
export const FIT_MAX_ZOOM = 1.25

/**
 * How far a fit is allowed to zoom out.
 *
 * A NODE IS NEVER DRAWN BELOW A SIZE ITS TEXT CAN BE READ AT. A fit answers the whole shape by
 * scaling it, and past a point what that answers with is a diagram of grey boxes -- the 14px
 * title is under ten pixels by a third of its size. A graph too big to fit at this zoom is
 * shown at this zoom and panned to, which is the reading that is worth having.
 */
export const FIT_MIN_ZOOM = 0.55

/** How far one press of a zoom control moves, as a factor on the zoom. */
export const ZOOM_STEP = 1.5

/** The zoom a canvas may be taken to by hand, either side of what a fit will do. */
export const MIN_ZOOM = 0.3
export const MAX_ZOOM = 2

/** What every fit on either canvas is made with, so the two cannot come to differ. */
export function fitOptionsFor(): { padding: number; minZoom: number; maxZoom: number; duration: number } {
    return { padding: FIT_PADDING, minZoom: FIT_MIN_ZOOM, maxZoom: FIT_MAX_ZOOM, duration: 0 }
}

/** The zoom a fit settles at, which is what it asked for held inside the two bounds. */
export function fittedZoom(zoom: number): number {
    return Math.min(FIT_MAX_ZOOM, Math.max(FIT_MIN_ZOOM, zoom))
}

/** Where one press of a zoom control lands, held inside what the canvas allows. */
export function steppedZoom(zoom: number, direction: 'in' | 'out'): number {
    const next = direction === 'in' ? zoom * ZOOM_STEP : zoom / ZOOM_STEP
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, next))
}

/**
 * What a canvas re-fits on: which nodes there are and where each of them was put.
 *
 * NOT THE STATE ON THEM. A step going from running to succeeded moves nothing, so the view it
 * is read in must not jump; adding a step to a document moves everything, so it must.
 */
export function viewportSignature(nodes: readonly { id: string; position?: { x: number; y: number } }[]): string {
    return nodes
        .map((node) => `${node.id}@${String(node.position?.x ?? 0)},${String(node.position?.y ?? 0)}`)
        .join('|')
}
