import { describe, expect, test } from 'vitest'

import {
    ACCENT_DOTS,
    FAILED,
    HEAD,
    LINKS,
    LIT_LINKS,
    MAX_ROW_STRETCH,
    MAX_SCALE,
    MIN_COLUMN_GAP,
    MIN_ROW_GAP,
    NODES,
    NODE_H,
    NODE_W,
    PAD_X,
    PAD_Y,
    edgePath,
    isLit,
    layout,
    linkKey,
    placedOf,
    type Layout,
} from '@/components/login/graph'

const ids = new Set(NODES.map((node) => node.id))

const spanOf = (values: number[]) => Math.max(...values) - Math.min(...values)
const NATURAL_W = spanOf(NODES.map((node) => node.x)) + 2 * PAD_X
const NATURAL_H = spanOf(NODES.map((node) => node.y)) + 2 * PAD_Y

/** The tightest pair of drawn steps whose boxes overlap horizontally. */
function tightestDrawnRowGap(placed: { x: number; y: number }[]): number {
    let tightest = Infinity
    for (const a of placed) {
        for (const b of placed) {
            if (a === b) continue
            if (Math.abs(a.x - b.x) >= NODE_W) continue
            tightest = Math.min(tightest, Math.abs(a.y - b.y))
        }
    }
    return tightest
}

/** The tightest pair of drawn columns, grouping the steps a nudge apart back into one. */
function tightestDrawnColumnGap(placed: { x: number }[]): number {
    const xs = placed.map((node) => node.x).toSorted((a, b) => a - b)
    const centres: number[] = []
    let group: number[] = []
    for (const x of xs) {
        if (group.length > 0 && x - group[group.length - 1] >= NODE_W) {
            centres.push(group.reduce((total, each) => total + each, 0) / group.length)
            group = []
        }
        group.push(x)
    }
    centres.push(group.reduce((total, each) => total + each, 0) / group.length)
    let tightest = Infinity
    for (let i = 1; i < centres.length; i += 1) {
        tightest = Math.min(tightest, centres[i] - centres[i - 1])
    }
    return tightest
}

describe('the login graph', () => {
    test('draws fourteen steps, each named once', () => {
        expect(NODES).toHaveLength(14)
        expect(ids.size).toBe(14)
    })

    test('joins only steps it draws', () => {
        for (const [from, to] of LINKS) {
            expect(ids.has(from)).toBe(true)
            expect(ids.has(to)).toBe(true)
        }
    })

    test('has no link twice', () => {
        expect(new Set(LINKS.map(linkKey)).size).toBe(LINKS.length)
    })

    test('lights the path the run took, and every lit link is a link', () => {
        expect(LIT_LINKS.map(linkKey)).toEqual([
            'S-A1',
            'S-A2',
            'S-A3',
            'A1-B2',
            'A2-B2',
            'A3-B3',
            'B2-C1',
            'B2-C2',
            'B3-C2',
            'B3-C3',
            'C1-D1',
            'C3-D2',
            'D1-T',
            'D2-T',
        ])
        const all = new Set(LINKS.map(linkKey))
        for (const link of LIT_LINKS) expect(all.has(linkKey(link))).toBe(true)
    })

    test('leaves the rest of the links unlit', () => {
        expect(LINKS.filter(isLit)).toHaveLength(14)
        expect(LINKS.filter((link) => !isLit(link))).toHaveLength(7)
    })

    test('has one head and one failed step', () => {
        expect(HEAD).toBe('T')
        expect(FAILED).toBe('C2')
        expect(ids.has(HEAD)).toBe(true)
        expect(ids.has(FAILED)).toBe(true)
        expect(LINKS.some(([, to]) => to === HEAD)).toBe(true)
        expect(LINKS.some(([from]) => from === HEAD)).toBe(false)
    })

    test('gives ten steps an accent dot and the other four something else', () => {
        expect([...ACCENT_DOTS].toSorted()).toEqual(
            ['A1', 'A2', 'A3', 'B2', 'B3', 'C1', 'C3', 'D1', 'D2', 'S'].toSorted(),
        )
        for (const id of ACCENT_DOTS) expect(ids.has(id)).toBe(true)
        expect(ACCENT_DOTS.has(HEAD)).toBe(false)
        expect(ACCENT_DOTS.has(FAILED)).toBe(false)
    })

    test('bends an edge from one box edge to the other, with level handles', () => {
        const { nodes } = layout(NODES, 900, 600)
        const from = placedOf(nodes, 'D1')
        const to = placedOf(nodes, 'T')
        const x1 = from.x + NODE_W / 2
        const x2 = to.x - NODE_W / 2
        const mid = x1 + (x2 - x1) / 2
        expect(edgePath(from, to)).toBe(`M${x1} ${from.y} C${mid} ${from.y}, ${mid} ${to.y}, ${x2} ${to.y}`)
    })
})

describe('the login graph laid out over a box', () => {
    test('fits the drawing at its own shape, and never magnifies it past the cap', () => {
        // A box a shade larger than the drawing: the scale is what fits, the rows have nothing
        // to take, and the columns are the table's own.
        const snug = layout(NODES, NATURAL_W * 1.2, NATURAL_H * 1.2)
        expect(snug.scale).toBeCloseTo(1.2, 6)
        expect(snug.width).toBeCloseTo(NATURAL_W, 1)
        expect(snug.height).toBeCloseTo(NATURAL_H, 1)
        for (const node of NODES) {
            const drawn = placedOf(snug.nodes, node.id)
            expect(drawn.x - PAD_X).toBeCloseTo(node.x - Math.min(...NODES.map((n) => n.x)), 1)
        }
        // A box far larger than the drawing in both directions stops at the cap.
        const huge = layout(NODES, NATURAL_W * 4, NATURAL_H * 4)
        expect(huge.scale).toBe(MAX_SCALE)
    })

    test('stretches the rows into a taller box, by no more than the cap, and never the columns', () => {
        const width = NATURAL_W
        const roomy = layout(NODES, width, NATURAL_H * 3)
        const columnsOf = (drawn: Layout) => NODES.map((node) => placedOf(drawn.nodes, node.id).x)
        // The rows stop at the cap however much height is going spare.
        expect(roomy.height).toBeCloseTo(NATURAL_H * MAX_ROW_STRETCH, 1)
        // Halfway there, the rows take exactly what the box has.
        const some = layout(NODES, width, NATURAL_H * 1.15)
        expect(some.height).toBeCloseTo(NATURAL_H * 1.15, 1)
        expect(some.scale).toBe(1)
        // The columns are the same in all three, because only the rows ever stretch.
        expect(columnsOf(roomy)).toEqual(columnsOf(some))
        expect(columnsOf(roomy)).toEqual(columnsOf(layout(NODES, width, NATURAL_H)))
    })

    test('splits what is left over evenly above and below, and centres the drawing across', () => {
        const height = NATURAL_H * 3
        const drawn = layout(NODES, NATURAL_W * 1.5, height)
        expect(drawn.scale).toBeCloseTo(1.5, 6)
        expect(drawn.offsetY).toBeCloseTo((height - drawn.height * drawn.scale) / 2, 1)
        expect(drawn.offsetY).toBeGreaterThan(0)
        expect(drawn.offsetX).toBeCloseTo(0, 1)
        // A box wider than the fitted drawing leaves the same ground either side of it.
        const wide = layout(NODES, NATURAL_W * 3, NATURAL_H)
        expect(wide.offsetX).toBeCloseTo((NATURAL_W * 3 - wide.width * wide.scale) / 2, 1)
        expect(wide.offsetX).toBeGreaterThan(0)
    })

    test('keeps every node box inside the box at a wide pane and a narrow one', () => {
        for (const [width, height] of [
            [900, 600],
            [700, 1100],
        ]) {
            const drawn = layout(NODES, width, height)
            expect(drawn.scale).toBeGreaterThanOrEqual(1)
            for (const node of drawn.nodes) {
                expect(node.x - NODE_W / 2).toBeGreaterThanOrEqual(0)
                expect(node.x + NODE_W / 2).toBeLessThanOrEqual(drawn.width)
                expect(node.y - NODE_H / 2).toBeGreaterThanOrEqual(0)
                expect(node.y + NODE_H / 2).toBeLessThanOrEqual(drawn.height)
            }
        }
    })

    test('never draws two steps of one column closer than the minimum row gap', () => {
        for (const height of [1100, 600, 320, 200, 90]) {
            const drawn = layout(NODES, 900, height)
            expect(tightestDrawnRowGap(drawn.nodes)).toBeGreaterThanOrEqual(MIN_ROW_GAP)
        }
    })

    test('never draws two columns closer than the minimum column gap', () => {
        for (const width of [1200, 900, 640, 380, 240]) {
            const drawn = layout(NODES, width, 600)
            expect(tightestDrawnColumnGap(drawn.nodes)).toBeGreaterThanOrEqual(MIN_COLUMN_GAP)
        }
    })

    test('shrinks the whole drawing uniformly when the box is smaller than the shape', () => {
        const roomy = layout(NODES, NATURAL_W, NATURAL_H)
        expect(roomy.scale).toBe(1)
        for (const [width, height] of [
            [900, 200],
            [380, 600],
        ]) {
            const cramped = layout(NODES, width, height)
            expect(cramped.scale).toBeLessThan(1)
            // What the scale meets is the box, in both directions: the drawing is laid out in the
            // space the shape needs and multiplied down, leaving no ground either way.
            expect(cramped.width * cramped.scale).toBeCloseTo(width, 1)
            expect(cramped.height * cramped.scale).toBeCloseTo(height, 1)
            // Uniform: every step keeps the fraction of the drawing it had at the roomy box.
            for (const node of roomy.nodes) {
                const tight = placedOf(cramped.nodes, node.id)
                expect((tight.x - PAD_X) / (cramped.width - 2 * PAD_X)).toBeCloseTo(
                    (node.x - PAD_X) / (roomy.width - 2 * PAD_X),
                    4,
                )
                expect((tight.y - PAD_Y) / (cramped.height - 2 * PAD_Y)).toBeCloseTo(
                    (node.y - PAD_Y) / (roomy.height - 2 * PAD_Y),
                    4,
                )
            }
        }
    })
})
