/**
 * The run drawn behind the login lockup, as data and as a layout over it.
 *
 * The table is a shape rather than a drawing: what a node carries is which column and which row
 * it sits in, read as a fraction of the table's own extent, and `layout` spends those fractions
 * across whatever box the pane hands it. A node keeps its size at every pane, so a shorter pane
 * loses ground between the rows rather than legibility, and only a box too short to hold the
 * rows at all shrinks the whole drawing.
 *
 * It is kept apart from the component so the lit set, the failed step, the head and the layout
 * are asserted in Node.
 */

/** A node's box. The dot sits `DOT_INSET` in from the left edge, the bar `BAR_INSET`. */
export const NODE_W = 66
export const NODE_H = 36
export const NODE_RADIUS = 9
export const DOT_R = 4
export const DOT_INSET = 14
export const BAR_INSET = 25
export const BAR_W = 26
export const BAR_H = 4
export const BAR_RADIUS = 2

export type Node = { id: string; x: number; y: number }

/** Every step, by the centre of its box. */
export const NODES: Node[] = [
    { id: 'S', x: 89, y: 393 },
    { id: 'A1', x: 217, y: 280 },
    { id: 'A2', x: 217, y: 393 },
    { id: 'A3', x: 217, y: 514 },
    { id: 'B1', x: 332, y: 225 },
    { id: 'B2', x: 342, y: 345 },
    { id: 'B3', x: 335, y: 467 },
    { id: 'B4', x: 335, y: 575 },
    { id: 'C1', x: 459, y: 285 },
    { id: 'C2', x: 459, y: 405 },
    { id: 'C3', x: 459, y: 527 },
    { id: 'D1', x: 568, y: 354 },
    { id: 'D2', x: 568, y: 471 },
    { id: 'T', x: 672, y: 405 },
]

export type Link = readonly [from: string, to: string]

/** Every dependency in the graph, source first. */
export const LINKS: Link[] = [
    ['S', 'A1'],
    ['S', 'A2'],
    ['S', 'A3'],
    ['A1', 'B1'],
    ['A1', 'B2'],
    ['A2', 'B2'],
    ['A2', 'B3'],
    ['A3', 'B3'],
    ['A3', 'B4'],
    ['B1', 'C1'],
    ['B2', 'C1'],
    ['B2', 'C2'],
    ['B3', 'C2'],
    ['B3', 'C3'],
    ['B4', 'C3'],
    ['C1', 'D1'],
    ['C2', 'D1'],
    ['C2', 'D2'],
    ['C3', 'D2'],
    ['D1', 'T'],
    ['D2', 'T'],
]

/** The links the run actually took, which are the ones drawn in the accent. */
export const LIT_LINKS: Link[] = [
    ['S', 'A1'],
    ['S', 'A2'],
    ['S', 'A3'],
    ['A1', 'B2'],
    ['A2', 'B2'],
    ['A3', 'B3'],
    ['B2', 'C1'],
    ['B2', 'C2'],
    ['B3', 'C2'],
    ['B3', 'C3'],
    ['C1', 'D1'],
    ['C3', 'D2'],
    ['D1', 'T'],
    ['D2', 'T'],
]

/** The step the run is on. */
export const HEAD = 'T'

/** The one step that failed. */
export const FAILED = 'C2'

/** The steps whose dot takes the accent; every other dot is muted. */
export const ACCENT_DOTS = new Set(['S', 'A1', 'A2', 'A3', 'B2', 'B3', 'C1', 'C3', 'D1', 'D2'])

export const linkKey = (link: Link) => `${link[0]}-${link[1]}`

const LIT_KEYS = new Set(LIT_LINKS.map(linkKey))

/** Whether a link is one the run took. */
export const isLit = (link: Link) => LIT_KEYS.has(linkKey(link))

/** The room kept clear inside the box, so no node's box touches an edge of it. */
export const PAD_X = 60
export const PAD_Y = 40

/** The closest two steps in one column are drawn, before the whole drawing shrinks instead. */
export const MIN_ROW_GAP = 52

/** The closest two columns are drawn, centre to centre, so a box never lands on its neighbour. */
export const MIN_COLUMN_GAP = 92

/** How far the drawing may be magnified past its own size, however wide the pane. */
export const MAX_SCALE = 1.5

/** How far the rows may be pulled apart past the spacing the drawing was scaled to. */
export const MAX_ROW_STRETCH = 1.3

export type Placed = { id: string; x: number; y: number }

export type Layout = {
    /** Every node at its centre, in the drawing's own space. */
    nodes: Placed[]
    /** The drawing's own size, before the scale below. */
    width: number
    height: number
    /** What the drawing is multiplied by, and where in the box that leaves it. */
    scale: number
    offsetX: number
    offsetY: number
}

function extent(values: number[]): { low: number; span: number } {
    const low = Math.min(...values)
    const high = Math.max(...values)
    return { low, span: high - low || 1 }
}

/**
 * Two steps are in one column when the table draws them within a box's width of each other, so
 * a stage whose boxes were nudged apart is still one column.
 */
function columns(nodes: Node[]): Node[][] {
    const sorted = nodes.toSorted((a, b) => a.x - b.x)
    const grouped: Node[][] = []
    let previous = Number.NEGATIVE_INFINITY
    for (const node of sorted) {
        if (node.x - previous >= NODE_W) grouped.push([])
        grouped[grouped.length - 1].push(node)
        previous = node.x
    }
    return grouped
}

/** The tightest pair of steps stacked in one column, as a fraction of the table's height. */
function tightestRowGap(nodes: Node[], span: number): number {
    let tightest = Infinity
    for (const column of columns(nodes)) {
        const ys = column.map((node) => node.y).toSorted((a, b) => a - b)
        for (let i = 1; i < ys.length; i += 1) tightest = Math.min(tightest, ys[i] - ys[i - 1])
    }
    return tightest === Infinity ? 1 : tightest / span
}

/** The tightest pair of neighbouring columns, as a fraction of the table's width. */
function tightestColumnGap(nodes: Node[], span: number): number {
    const centres = columns(nodes).map(
        (column) => column.reduce((total, node) => total + node.x, 0) / column.length,
    )
    let tightest = Infinity
    for (let i = 1; i < centres.length; i += 1) {
        tightest = Math.min(tightest, centres[i] - centres[i - 1])
    }
    return tightest === Infinity ? 1 : tightest / span
}

const round = (value: number) => Math.round(value * 100) / 100

/**
 * The table drawn at its own size in a box of `width` by `height` pixels.
 *
 * IT IS FITTED, NOT SPREAD. The drawing has a natural shape -- the table's own extent plus the
 * padding -- and it is scaled uniformly to fit the box, bounded above by `MAX_SCALE` so a wide
 * pane does not magnify it into a poster. Spending the fractions across the box instead would
 * pull the rows apart until the edges ran long and the run went sparse.
 *
 * THEN THE ROWS TAKE SOME OF WHAT IS LEFT. A box taller than the fitted drawing stretches the
 * row spacing by up to `MAX_ROW_STRETCH`, and the columns never stretch at all: what a taller
 * pane is worth is a little more air between the ranks, not a different graph. Whatever height
 * is still over is split evenly above and below, so the drawing sits centred in its box.
 *
 * A BOX SMALLER THAN THE SHAPE NEEDS IS THE LAST RESORT, and it is the fallback this had
 * before: the fractions are spread across the box and the whole drawing multiplied down to the
 * largest scale that keeps a column's steps `MIN_ROW_GAP` apart and its columns
 * `MIN_COLUMN_GAP` apart, which is the only case in which a node is smaller than it states.
 */
export function layout(nodes: Node[], width: number, height: number): Layout {
    const across = extent(nodes.map((node) => node.x))
    const down = extent(nodes.map((node) => node.y))
    const naturalWidth = across.span + 2 * PAD_X
    const naturalHeight = down.span + 2 * PAD_Y
    const floor = Math.min(
        1,
        width / (MIN_COLUMN_GAP / tightestColumnGap(nodes, across.span) + 2 * PAD_X),
        height / (MIN_ROW_GAP / tightestRowGap(nodes, down.span) + 2 * PAD_Y),
    )
    const fitted = Math.min(MAX_SCALE, width / naturalWidth, height / naturalHeight)
    if (fitted < floor) return spread(nodes, across, down, width, height, floor)

    const stretch = Math.min(MAX_ROW_STRETCH, height / (naturalHeight * fitted))
    const drawnHeight = naturalHeight * stretch
    return {
        nodes: nodes.map((node) => ({
            id: node.id,
            x: round(PAD_X + (node.x - across.low)),
            y: round((PAD_Y + (node.y - down.low)) * stretch),
        })),
        width: round(naturalWidth),
        height: round(drawnHeight),
        scale: fitted,
        offsetX: round((width - naturalWidth * fitted) / 2),
        offsetY: round((height - drawnHeight * fitted) / 2),
    }
}

/** The fallback: every fraction spread across a box too small to hold the drawing. */
function spread(
    nodes: Node[],
    across: { low: number; span: number },
    down: { low: number; span: number },
    width: number,
    height: number,
    scale: number,
): Layout {
    const drawnWidth = width / scale
    const drawnHeight = height / scale
    const innerWidth = Math.max(drawnWidth - 2 * PAD_X, 1)
    const innerHeight = Math.max(drawnHeight - 2 * PAD_Y, 1)
    return {
        nodes: nodes.map((node) => ({
            id: node.id,
            x: round(PAD_X + ((node.x - across.low) / across.span) * innerWidth),
            y: round(PAD_Y + ((node.y - down.low) / down.span) * innerHeight),
        })),
        width: round(drawnWidth),
        height: round(drawnHeight),
        scale,
        offsetX: 0,
        offsetY: 0,
    }
}

export function placedOf(placed: Placed[], id: string): Placed {
    const node = placed.find((candidate) => candidate.id === id)
    if (node === undefined) throw new Error(`no node ${id}`)
    return node
}

/**
 * From the right edge of the source to the left edge of the target, with both handles at half
 * the horizontal distance, so an edge leaves and arrives level however far it climbs.
 */
export function edgePath(from: Placed, to: Placed): string {
    const x1 = from.x + NODE_W / 2
    const x2 = to.x - NODE_W / 2
    const dx = x2 - x1
    return `M${x1} ${from.y} C${x1 + dx / 2} ${from.y}, ${x2 - dx / 2} ${to.y}, ${x2} ${to.y}`
}

/** The arcs behind the graph: one family of circles centred off the box's right edge. */
export function arcsFor(width: number, height: number): { cx: number; cy: number; radii: number[] } {
    return {
        cx: round(width * 1.3),
        cy: round(height / 2),
        radii: Array.from({ length: 11 }, (_, step) => round(height * (0.64 + step * 0.098))),
    }
}
