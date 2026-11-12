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

/** How wide a node is drawn when a screen does not say: the width before words decided it. */
export const NODE_WIDTH = 160

/** The narrowest a node is drawn, however short its words. */
export const NODE_MIN_WIDTH = 96

/** The widest a node is drawn; past it a word truncates and carries its whole value on hover. */
export const NODE_MAX_WIDTH = 360

/**
 * The four faces a node's words are set in: the title at 12px and every other word at 11px, each
 * in mono where it is a key and in the sans where it is prose.
 */
export type TextFace = 'title-mono' | 'title-sans' | 'small-mono' | 'small-sans'

/** How wide a run of text is drawn in one face, in pixels. */
export type Measure = (text: string, face: TextFace) => number

/** The pixel size of each face. */
export const FACE_SIZE: Record<TextFace, number> = {
    'title-mono': 12,
    'title-sans': 12,
    'small-mono': 11,
    'small-sans': 11,
}

/**
 * A width read off the characters, for where no font can be measured.
 *
 * IBM Plex Mono advances 0.6em per character, so a mono width is exact; the sans is given the
 * width of its wider letters, so a width read in Node is never narrower than the page's.
 */
export const measureByCharacters: Measure = (text, face) =>
    text.length * FACE_SIZE[face] * (face.endsWith('mono') ? 0.6 : 0.62)

/** A node's padding and border, with room for the 1.5px edge a failed box wears. */
export const NODE_CHROME = 22

/** The gap between two things on one line of a node. */
export const NODE_GAP = 6

/** What a state's dot takes. */
export const DOT_WIDTH = 8

/** What a 12px glyph takes. */
export const GLYPH_WIDTH = 12

/**
 * How wide a node is drawn for none of its lines to be cut: the widest line plus the box's chrome,
 * held between the floor and the cap.
 */
export function boxWidth(lines: readonly number[]): number {
    const widest = lines.reduce((most, line) => Math.max(most, line), 0)
    return Math.min(NODE_MAX_WIDTH, Math.max(NODE_MIN_WIDTH, Math.ceil(widest + NODE_CHROME)))
}

/**
 * How wide a node has to be for none of its words to be cut: the longer of the title with its dot
 * and the line under it with whatever stands at its end.
 */
export function nodeWidth(
    title: string,
    line: string,
    lineExtra = 0,
    measure: Measure = measureByCharacters,
): number {
    return boxWidth([
        measure(title, 'title-mono') + NODE_GAP + DOT_WIDTH,
        measure(line, 'small-mono') + lineExtra,
    ])
}

/** What a fan-out marker at the end of a node's line takes: the gap, its glyph, and its word. */
export function fanOutRoom(word: string, measure: Measure = measureByCharacters): number {
    return Math.ceil(NODE_GAP + GLYPH_WIDTH + 4 + measure(word, 'small-mono'))
}

/** How tall an ordinary node is: its title, one line under it, and its padding. */
export const NODE_HEIGHT = 44

/** One node to place: what it is called, and how wide and how tall it will be drawn. */
export interface LayoutNode {
    id: string
    /** How wide the node is drawn; `NODE_WIDTH` where a screen does not say. */
    width?: number
    height: number
}

/** How wide one node is drawn. */
function widthOf(node: LayoutNode): number {
    return node.width ?? NODE_WIDTH
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

/** One stretch of a routed edge, as elk answers it. */
export interface ElkSection {
    startPoint: GraphPoint
    endPoint: GraphPoint
    bendPoints?: GraphPoint[]
}

/** The subset of elk's answer this module reads. */
export interface ElkLaidOut {
    children?: { id: string; x?: number; y?: number; width?: number; height?: number }[]
    edges?: { id: string; sections?: ElkSection[] }[]
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

/** A point in the graph's own coordinates. */
export interface GraphPoint {
    x: number
    y: number
}

/** One edge, named by the pair it joins, with the route elk drew for it once it has. */
export interface PlacedEdge {
    id: string
    source: string
    target: string
    /** Where the edge starts, bends and ends, in the graph's coordinates. */
    points?: GraphPoint[]
}

/** A whole graph, placed. */
export interface PlacedGraph {
    nodes: PlacedNode[]
    edges: PlacedEdge[]
}

/** How much canvas one rank takes: a node and the gap to the next rank. */
export const RANK_SPACING = 28

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
export const WRAP_WIDTH = 1120

/**
 * What elk is told when a graph is too wide to draw in one row: cut the layering into chunks
 * and stack them, aiming at a shape wider than it is tall, the way a canvas is.
 */
export const WRAP_OPTIONS: Record<string, string> = {
    'elk.layered.wrapping.strategy': 'MULTI_EDGE',
    'elk.aspectRatio': '2.0',
    'elk.layered.wrapping.additionalEdgeSpacing': '24',
}

/** How deep into the graph each node is: one more than the deepest thing it waits for. */
function ranksOf(shape: LayoutShape): Map<string, number> {
    const known = new Set(shape.nodes.map((node) => node.id))
    const before = new Map<string, string[]>()
    for (const [from, to] of shape.edges) {
        if (!known.has(from) || !known.has(to)) continue
        before.set(to, [...(before.get(to) ?? []), from])
    }

    const ranks = new Map<string, number>()
    const rankOf = (id: string, path: ReadonlySet<string>): number => {
        const held = ranks.get(id)
        if (held !== undefined) return held
        // A shape that has somehow closed a loop is ranked rather than walked forever.
        if (path.has(id)) return 0
        const onward = new Set([...path, id])
        const rank = (before.get(id) ?? []).reduce(
            (most, from) => Math.max(most, rankOf(from, onward) + 1),
            0,
        )
        ranks.set(id, rank)
        return rank
    }

    for (const node of shape.nodes) rankOf(node.id, new Set())
    return ranks
}

/** How many ranks deep a shape is: the longest chain of dependencies in it. */
export function rankDepth(shape: LayoutShape): number {
    return [...ranksOf(shape).values()].reduce((most, rank) => Math.max(most, rank + 1), 0)
}

/** How wide each rank is: the widest node standing in it. */
function rankWidths(shape: LayoutShape, ranks: Map<string, number>): number[] {
    const widths: number[] = []
    for (const node of shape.nodes) {
        const rank = ranks.get(node.id) ?? 0
        widths[rank] = Math.max(widths[rank] ?? 0, widthOf(node))
    }
    return Array.from(widths, (width) => width ?? 0)
}

/** How wide a shape would be drawn in one left-to-right row. */
export function unwrappedWidth(shape: LayoutShape, rankGap: number = RANK_SPACING): number {
    const widths = rankWidths(shape, ranksOf(shape))
    if (widths.length === 0) return 0
    return widths.reduce((sum, width) => sum + width, 0) + (widths.length - 1) * rankGap
}

/** Which way the ranks run: left to right, or top to bottom. */
export type LayoutDirection = 'right' | 'down'

/** How an edge is drawn: the canvas's own stepped line, routed around the boxes, or curved. */
export type EdgeRouting = 'default' | 'orthogonal' | 'splines'

/** How much room is left between boxes and between ranks. */
export type LayoutSpacing = 'default' | 'compact' | 'roomy'

/** How a view lays its graph out, which a reader may change for the visit. */
export interface LayoutChoice {
    direction: LayoutDirection
    routing: EdgeRouting
    spacing: LayoutSpacing
}

/** What every view opens on. */
export const DEFAULT_LAYOUT: LayoutChoice = { direction: 'right', routing: 'default', spacing: 'default' }

/** The gaps each spacing asks for: between two boxes of a rank, and between two ranks. */
export const SPACINGS: Record<LayoutSpacing, { node: number; rank: number }> = {
    compact: { node: 12, rank: 20 },
    default: { node: NODE_SPACING, rank: RANK_SPACING },
    roomy: { node: 36, rank: 64 },
}

/** How far apart two routed edges run, and how far one keeps from a box it passes. */
export const EDGE_SPACING = 10
export const EDGE_NODE_SPACING = 14

/** Whether a choice is the one every view opens on. */
export function isDefaultLayout(choice: LayoutChoice): boolean {
    return (
        choice.direction === DEFAULT_LAYOUT.direction &&
        choice.routing === DEFAULT_LAYOUT.routing &&
        choice.spacing === DEFAULT_LAYOUT.spacing
    )
}

/** What elk is told about where every edge leaves, bends and arrives. */
function routingOptions(routing: EdgeRouting): Record<string, string> {
    if (routing === 'default') return { 'elk.edgeRouting': 'POLYLINE' }
    return {
        'elk.edgeRouting': routing === 'orthogonal' ? 'ORTHOGONAL' : 'SPLINES',
        // Merged, five edges into one step are drawn as one trunk.
        'elk.layered.mergeEdges': 'false',
        'elk.spacing.edgeEdge': String(EDGE_SPACING),
        'elk.spacing.edgeNode': String(EDGE_NODE_SPACING),
        'elk.layered.spacing.edgeEdgeBetweenLayers': String(EDGE_SPACING),
        'elk.layered.spacing.edgeNodeBetweenLayers': String(EDGE_NODE_SPACING),
        ...(routing === 'splines' ? { 'elk.layered.edgeRouting.splines.mode': 'CONSERVATIVE' } : {}),
    }
}

/**
 * The options one shape is placed with: the layered ones, plus wrapping when it is too wide.
 *
 * The default choice is exactly the layout every canvas opens on. A graph drawn top to bottom is
 * never wrapped: its depth runs down the page, which is the way a page scrolls.
 */
export function layoutOptionsFor(
    shape: LayoutShape,
    choice: LayoutChoice = DEFAULT_LAYOUT,
): Record<string, string> {
    const gaps = SPACINGS[choice.spacing]
    const wraps = choice.direction === 'right' && unwrappedWidth(shape, gaps.rank) > WRAP_WIDTH
    if (isDefaultLayout(choice)) return wraps ? { ...LAYOUT_OPTIONS, ...WRAP_OPTIONS } : LAYOUT_OPTIONS
    return {
        ...LAYOUT_OPTIONS,
        'elk.direction': choice.direction === 'right' ? 'RIGHT' : 'DOWN',
        'elk.layered.spacing.nodeNodeBetweenLayers': String(gaps.rank),
        'elk.spacing.nodeNode': String(gaps.node),
        ...routingOptions(choice.routing),
        ...(wraps ? WRAP_OPTIONS : {}),
    }
}

/**
 * What decides the geometry: which nodes there are, how tall each is, and what joins them.
 *
 * A graph is re-placed when this string changes and not when anything else does, so a step
 * going from running to succeeded, or a config field being typed into, moves no box.
 */
export function signatureOf(shape: LayoutShape, choice: LayoutChoice = DEFAULT_LAYOUT): string {
    return [
        shape.nodes.map((node) => `${node.id}:${String(widthOf(node))}x${String(node.height)}`).join(','),
        shape.edges.map(([from, to]) => `${from}>${to}`).join(','),
        `${choice.direction}/${choice.routing}/${choice.spacing}`,
    ].join('|')
}

/** The graph elk is handed: one child per node, one edge per dependency. */
export function toElkGraph(shape: LayoutShape, choice: LayoutChoice = DEFAULT_LAYOUT): ElkGraph {
    const known = new Set(shape.nodes.map((node) => node.id))
    return {
        id: 'dag',
        layoutOptions: layoutOptionsFor(shape, choice),
        children: shape.nodes.map((node) => ({ id: node.id, width: widthOf(node), height: node.height })),
        // An edge to or from a node the shape does not carry would be an edge elk cannot place.
        edges: shape.edges
            .filter(([from, to]) => known.has(from) && known.has(to))
            .map(([from, to]) => ({ id: `${from}->${to}`, sources: [from], targets: [to] })),
    }
}

/** The edges of a placed graph: every pair the shape carries both ends of. */
function placedEdges(shape: LayoutShape): PlacedEdge[] {
    const known = new Set(shape.nodes.map((node) => node.id))
    return shape.edges
        .filter(([from, to]) => known.has(from) && known.has(to))
        .map(([from, to]) => ({ id: `${from}->${to}`, source: from, target: to }))
}

/**
 * Read elk's answer back as positions.
 *
 * A child elk placed nowhere is placed at the origin rather than dropped: a node missing from
 * the graph is a step missing from the screen, which is worse than one drawn in the wrong place.
 */
export function fromElkGraph(shape: LayoutShape, laid: ElkLaidOut): PlacedGraph {
    const placed = new Map((laid.children ?? []).map((child) => [child.id, child]))
    const routes = new Map((laid.edges ?? []).map((edge) => [edge.id, routeOf(edge.sections ?? [])]))
    return {
        nodes: shape.nodes.map((node) => {
            const child = placed.get(node.id)
            return {
                id: node.id,
                x: child?.x ?? 0,
                y: child?.y ?? 0,
                width: child?.width ?? widthOf(node),
                height: child?.height ?? node.height,
            }
        }),
        edges: placedEdges(shape).map((edge) => {
            const points = routes.get(edge.id)
            if (points !== undefined && points.length >= 2) edge.points = points
            return edge
        }),
    }
}

/** An edge's sections joined into one run of points, start to end. */
function routeOf(sections: readonly ElkSection[]): GraphPoint[] {
    return sections.flatMap((section, index) => [
        ...(index === 0 ? [section.startPoint] : []),
        ...(section.bendPoints ?? []),
        section.endPoint,
    ])
}

/**
 * Where each rank stands when a shape is placed by hand: which row, and how far along it.
 *
 * A row takes ranks until the next would carry it past `WRAP_WIDTH`, and never fewer than one.
 */
function rankColumns(widths: readonly number[], wrapping: boolean): { row: number; x: number }[] {
    const placed: { row: number; x: number }[] = []
    let row = 0
    let x = 0
    for (const width of widths) {
        if (wrapping && x > 0 && x + width > WRAP_WIDTH) {
            row += 1
            x = 0
        }
        placed.push({ row, x })
        x += width + RANK_SPACING
    }
    return placed
}

/**
 * The same shape placed without elk: one column per rank, each stacked down the canvas.
 *
 * WHAT A CANVAS DRAWS UNTIL ELK ANSWERS. elk is fetched the first time a canvas asks for
 * geometry, and a graph that waits for the fetch is a screen with nothing on it -- so the ranks
 * are counted here instead and every box is drawn from the first frame, at the spacing and the
 * widths elk is asked for. It balances no row and crosses whatever edges cross, which is the
 * whole of what elk is for; when the answer arrives the boxes move to it.
 *
 * A NODE SITS ONE COLUMN RIGHT OF EVERYTHING IT WAITS FOR, so the reading is left to right
 * before and after, and a shape too wide for one row is cut into rows at the same `WRAP_WIDTH`
 * elk is handed -- a graph that would be fitted at a zoom its text cannot be read at is not one
 * to open on.
 */
export function placedByRank(shape: LayoutShape, choice: LayoutChoice = DEFAULT_LAYOUT): PlacedGraph {
    if (choice.direction === 'down') return placedDownByRank(shape, SPACINGS[choice.spacing])
    const ranks = ranksOf(shape)
    const wrapping = unwrappedWidth(shape) > WRAP_WIDTH
    const columns = rankColumns(rankWidths(shape, ranks), wrapping)

    // Every box in the row and column its rank puts it in, stacked where two share one.
    const nextTop = new Map<string, number>()
    const rowHeights = new Map<number, number>()
    const stacked = shape.nodes.map((node) => {
        const rank = ranks.get(node.id) ?? 0
        const row = columns[rank]?.row ?? 0
        const column = columns[rank]?.x ?? 0
        const key = `${String(row)}:${String(column)}`
        const top = nextTop.get(key) ?? 0
        nextTop.set(key, top + node.height + NODE_SPACING)
        rowHeights.set(row, Math.max(rowHeights.get(row) ?? 0, top + node.height))
        return { node, row, column, top }
    })

    // What each row starts at, which is every row above it and the gap between them.
    const rowTops = new Map<number, number>()
    let above = 0
    for (const row of [...rowHeights.keys()].toSorted((one, other) => one - other)) {
        rowTops.set(row, above)
        above += (rowHeights.get(row) ?? 0) + RANK_SPACING
    }

    return {
        nodes: stacked.map(({ node, row, column, top }) => ({
            id: node.id,
            x: column,
            y: top + (rowTops.get(row) ?? 0),
            width: widthOf(node),
            height: node.height,
        })),
        edges: placedEdges(shape),
    }
}

/** The same shape placed without elk, top to bottom: one row per rank, side by side within it. */
function placedDownByRank(shape: LayoutShape, gaps: { node: number; rank: number }): PlacedGraph {
    const ranks = ranksOf(shape)
    const rowHeights: number[] = []
    for (const node of shape.nodes) {
        const rank = ranks.get(node.id) ?? 0
        rowHeights[rank] = Math.max(rowHeights[rank] ?? 0, node.height)
    }
    const rowTops: number[] = []
    let above = 0
    for (const [rank, tallest] of Array.from(rowHeights, (row) => row ?? 0).entries()) {
        rowTops[rank] = above
        above += tallest + gaps.rank
    }
    const nextLeft = new Map<number, number>()
    return {
        nodes: shape.nodes.map((node) => {
            const rank = ranks.get(node.id) ?? 0
            const left = nextLeft.get(rank) ?? 0
            nextLeft.set(rank, left + widthOf(node) + gaps.node)
            return { id: node.id, x: left, y: rowTops[rank] ?? 0, width: widthOf(node), height: node.height }
        }),
        edges: placedEdges(shape),
    }
}

/** Place a graph. */
export async function layoutDag(
    shape: LayoutShape,
    elk: ElkEngine,
    choice: LayoutChoice = DEFAULT_LAYOUT,
): Promise<PlacedGraph> {
    if (shape.nodes.length === 0) return { nodes: [], edges: [] }
    return fromElkGraph(shape, await elk.layout(toElkGraph(shape, choice)))
}

/**
 * The path an edge elk routed is drawn along.
 *
 * A routed edge is straight runs turned on a small radius at each bend. A curved one is what elk
 * answers for splines: the start, then every further three points one cubic segment. A curve whose
 * points are not in threes is drawn as a routed one.
 */
export function routedPath(points: readonly GraphPoint[], curved: boolean, radius = 6): string {
    const first = points[0]
    const last = points[points.length - 1]
    if (first === undefined || last === undefined || points.length < 2) return ''
    if (curved && (points.length - 1) % 3 === 0) {
        const segments: string[] = []
        for (let index = 1; index + 2 < points.length; index += 3) {
            const [one, two, end] = points.slice(index, index + 3) as [GraphPoint, GraphPoint, GraphPoint]
            segments.push(`C ${pointOf(one)}, ${pointOf(two)}, ${pointOf(end)}`)
        }
        return `M ${pointOf(first)} ${segments.join(' ')}`
    }
    const parts = [`M ${pointOf(first)}`]
    for (let index = 1; index < points.length - 1; index += 1) {
        const [before, corner, after] = points.slice(index - 1, index + 2) as [
            GraphPoint,
            GraphPoint,
            GraphPoint,
        ]
        const inward = Math.min(radius, distance(before, corner) / 2, distance(corner, after) / 2)
        parts.push(`L ${pointOf(toward(corner, before, inward))}`)
        parts.push(`Q ${pointOf(corner)} ${pointOf(toward(corner, after, inward))}`)
    }
    parts.push(`L ${pointOf(last)}`)
    return parts.join(' ')
}

/** How far apart two points are. */
function distance(one: GraphPoint, other: GraphPoint): number {
    return Math.hypot(other.x - one.x, other.y - one.y)
}

/** The point `by` along the way from one point towards another. */
function toward(from: GraphPoint, to: GraphPoint, by: number): GraphPoint {
    const length = distance(from, to)
    if (length === 0) return from
    return { x: from.x + ((to.x - from.x) * by) / length, y: from.y + ((to.y - from.y) * by) / length }
}

/** A point as a path writes it, to a tenth of a pixel. */
function pointOf(point: GraphPoint): string {
    return `${String(Math.round(point.x * 10) / 10)} ${String(Math.round(point.y * 10) / 10)}`
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
 * How far a fit is allowed to zoom in: never past a box's own size.
 *
 * Fitting a small shape to a large space magnifies it until a step is the size of a card, which
 * says the pipeline is bigger than it is, so a graph of two boxes opens at the size a graph of
 * twenty does and a fifty-step one is still zoomed out until all of it is on screen.
 */
export const FIT_MAX_ZOOM = 1

/**
 * How far a fit is allowed to zoom out.
 *
 * A NODE IS NEVER DRAWN BELOW A SIZE ITS TEXT CAN BE READ AT: a 13px title stays at 10.4px and an
 * 11px word at 8.8px. A graph too big to fit at this zoom is shown at this zoom and panned to.
 */
export const FIT_MIN_ZOOM = 0.8

/** The ground a fitted canvas keeps above and below its drawing, in pixels. */
export const FITTED_GROUND = 40

/** The shortest a fitted canvas is drawn, so a graph of one box is not a sliver. */
export const FITTED_MIN_HEIGHT = 96

/**
 * How tall a canvas fitted to its drawing is, at the width it was given.
 *
 * The drawing is scaled down where it is wider than the canvas and never up past its own size,
 * and the canvas is as tall as the drawing at that zoom with its ground around it -- never shorter
 * than a fit with its padding would need, so the fit settles at the same zoom the height assumed.
 */
export function fittedHeight(drawing: { width: number; height: number }, width: number): number {
    if (drawing.width <= 0 || drawing.height <= 0 || width <= 0) return FITTED_MIN_HEIGHT
    const zoom = fittedZoom(Math.min(FIT_MAX_ZOOM, width / (drawing.width * (1 + FIT_PADDING))))
    const tall = Math.max(drawing.height * zoom + FITTED_GROUND, drawing.height * zoom * (1 + FIT_PADDING))
    return Math.max(FITTED_MIN_HEIGHT, Math.ceil(tall))
}

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

/** How far from the canvas's edge a graph past the floor starts, in pixels. */
export const OVERFLOW_MARGIN = 24

/** A pan and a zoom, as React Flow holds them. */
export interface GraphView {
    x: number
    y: number
    zoom: number
}

/** The box a graph's nodes take up, in the graph's own coordinates. */
export interface GraphBounds {
    x: number
    y: number
    width: number
    height: number
}

/**
 * Where a fitted view stands once what does not fit has been hung off the far edges.
 *
 * A fit centres the graph, so the canvas's own size is read back from where it put the centre. An
 * axis the graph fits on stays centred; on one it does not, the graph's start stands at the margin.
 */
export function startOfOverflow(view: GraphView, bounds: GraphBounds): GraphView {
    const place = (at: number, start: number, length: number): number => {
        const drawn = length * view.zoom
        const canvas = 2 * at + 2 * start * view.zoom + drawn
        return drawn <= canvas ? at : OVERFLOW_MARGIN - start * view.zoom
    }
    return {
        x: place(view.x, bounds.x, bounds.width),
        y: place(view.y, bounds.y, bounds.height),
        zoom: view.zoom,
    }
}

/** The most one wheel event zooms a canvas on a page by, either way. */
export const WHEEL_ZOOM_LIMIT = 1.15

/**
 * The factor one wheel event zooms a canvas on a page by, where a wheel zooms it.
 *
 * A pinch arrives as many events of a few pixels and a mouse wheel as notches of a hundred, so the
 * delta is read in pixels and each event is held to `WHEEL_ZOOM_LIMIT`: a notch is one step, and a
 * pinch follows the fingers.
 */
export function wheelZoomFactor(deltaY: number, deltaMode = 0): number {
    const pixels = deltaMode === 1 ? deltaY * 16 : deltaMode === 2 ? deltaY * 400 : deltaY
    const factor = Math.exp(-pixels * 0.01)
    return Math.min(WHEEL_ZOOM_LIMIT, Math.max(1 / WHEEL_ZOOM_LIMIT, factor))
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
export function viewportSignature(
    nodes: readonly { id: string; position?: { x: number; y: number } }[],
): string {
    return nodes
        .map((node) => `${node.id}@${String(node.position?.x ?? 0)},${String(node.position?.y ?? 0)}`)
        .join('|')
}

/** Where a canvas is looking, as React Flow states it: a pan in screen pixels and a zoom. */
export interface CanvasView {
    x: number
    y: number
    zoom: number
}

/**
 * Whether a gesture moved the view at all.
 *
 * A press on the ground, or on a box that cannot be dragged, starts a pan that goes nowhere,
 * and only a view that changed is one the reader took over.
 */
export function viewMoved(from: CanvasView, to: CanvasView): boolean {
    return from.x !== to.x || from.y !== to.y || from.zoom !== to.zoom
}

/**
 * The flow point to centre a canvas on so a box outside it comes into view, or null when the
 * whole box is already on the canvas.
 *
 * `box` is in flow coordinates and `canvas` in screen pixels; the zoom stays what it is.
 */
export function revealPoint(
    box: { x: number; y: number; width: number; height: number },
    view: CanvasView,
    canvas: { width: number; height: number },
): { x: number; y: number } | null {
    const left = box.x * view.zoom + view.x
    const top = box.y * view.zoom + view.y
    const right = left + box.width * view.zoom
    const bottom = top + box.height * view.zoom
    if (left >= 0 && top >= 0 && right <= canvas.width && bottom <= canvas.height) return null
    return { x: box.x + box.width / 2, y: box.y + box.height / 2 }
}
