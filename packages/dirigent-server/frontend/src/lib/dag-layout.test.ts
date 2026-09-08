import { describe, expect, test } from 'vitest'

import {
    FIT_MAX_ZOOM,
    FIT_MIN_ZOOM,
    LAYOUT_OPTIONS,
    MAX_ZOOM,
    MIN_ZOOM,
    NODE_HEIGHT,
    NODE_WIDTH,
    RANK_SPACING,
    STRIP_HEIGHT,
    WRAP_OPTIONS,
    WRAP_WIDTH,
    drawnSize,
    fitOptionsFor,
    fittedZoom,
    fromElkGraph,
    heightOf,
    layoutDag,
    layoutOptionsFor,
    rankDepth,
    signatureOf,
    steppedZoom,
    toElkGraph,
    unwrappedWidth,
    type ElkEngine,
    type ElkGraph,
    type LayoutShape,
} from '@/lib/dag-layout'

function node(id: string, height: number = NODE_HEIGHT) {
    return { id, height }
}

const CHAIN: LayoutShape = {
    nodes: [node('parse'), node('active'), node('report')],
    edges: [
        ['parse', 'active'],
        ['active', 'report'],
    ],
}

/**
 * An elk that places every child on one row, in the order it was given them.
 *
 * ELK IS NOT LOADED HERE. What is worth testing is the conversation with it -- what is sent and
 * what is read back -- and elk itself is a large bundle that would need a worker. The engine is
 * a parameter for exactly this reason.
 */
function rowEngine(): ElkEngine & { seen: ElkGraph[] } {
    const seen: ElkGraph[] = []
    return {
        seen,
        layout: (graph) => {
            seen.push(graph)
            return Promise.resolve({
                children: graph.children.map((child, index) => ({
                    id: child.id,
                    x: index * 300,
                    y: 0,
                    width: child.width,
                    height: child.height,
                })),
            })
        },
    }
}

describe('how tall a node is', () => {
    test('is three lines for an ordinary step', () => {
        expect(heightOf(false)).toBe(NODE_HEIGHT)
    })

    test('is that plus the strip for a fan-out step, which draws its elements inside itself', () => {
        expect(heightOf(true)).toBe(NODE_HEIGHT + STRIP_HEIGHT)
    })
})

describe('what decides the geometry', () => {
    test('is the nodes, their heights, and the edges, and nothing else about them', () => {
        expect(signatureOf(CHAIN)).toBe(signatureOf({ nodes: [...CHAIN.nodes], edges: [...CHAIN.edges] }))
    })

    test('changes when a node is added, which is when the canvas has to be placed again', () => {
        const grown: LayoutShape = { nodes: [...CHAIN.nodes, node('as_csv')], edges: CHAIN.edges }
        expect(signatureOf(grown)).not.toBe(signatureOf(CHAIN))
    })

    test('changes when a node grows an item strip, because the box it needs is taller', () => {
        const fanned: LayoutShape = { nodes: [node('push', heightOf(true))], edges: [] }
        expect(signatureOf(fanned)).not.toBe(signatureOf({ nodes: [node('push')], edges: [] }))
    })
})

describe('the graph elk is handed', () => {
    test('is one child per node, each at the size it will be drawn', () => {
        const graph = toElkGraph(CHAIN)
        expect(graph.children.map((child) => child.id)).toEqual(['parse', 'active', 'report'])
        expect(graph.children[0]).toEqual({ id: 'parse', width: NODE_WIDTH, height: NODE_HEIGHT })
    })

    test('is laid out layered and left to right, which is the direction a run reads in', () => {
        expect(toElkGraph(CHAIN).layoutOptions).toEqual(LAYOUT_OPTIONS)
        expect(LAYOUT_OPTIONS['elk.direction']).toBe('RIGHT')
        expect(LAYOUT_OPTIONS['elk.algorithm']).toBe('layered')
    })

    test('is one edge per dependency, named by the pair it joins', () => {
        expect(toElkGraph(CHAIN).edges).toEqual([
            { id: 'parse->active', sources: ['parse'], targets: ['active'] },
            { id: 'active->report', sources: ['active'], targets: ['report'] },
        ])
    })

    test('drops an edge naming a node the shape does not carry, which elk could not place', () => {
        const broken: LayoutShape = { nodes: [node('parse')], edges: [['parse', 'gone']] }
        expect(toElkGraph(broken).edges).toEqual([])
    })

    test('gives a fan-out step the room its item strip needs', () => {
        const fanned: LayoutShape = { nodes: [node('push', heightOf(true))], edges: [] }
        expect(toElkGraph(fanned).children[0]?.height).toBe(NODE_HEIGHT + STRIP_HEIGHT)
    })
})

describe("reading elk's answer", () => {
    test('places every node the shape carries', () => {
        const laid = fromElkGraph(CHAIN, {
            children: [
                { id: 'parse', x: 0, y: 0, width: NODE_WIDTH, height: NODE_HEIGHT },
                { id: 'active', x: 300, y: 0, width: NODE_WIDTH, height: NODE_HEIGHT },
                { id: 'report', x: 600, y: 40, width: NODE_WIDTH, height: NODE_HEIGHT },
            ],
        })

        expect(laid.nodes.map((one) => one.id)).toEqual(['parse', 'active', 'report'])
        expect(laid.nodes[2]).toEqual({ id: 'report', x: 600, y: 40, width: NODE_WIDTH, height: NODE_HEIGHT })
    })

    test('draws a node elk placed nowhere at the origin rather than dropping it', () => {
        // A node missing from the canvas is a step missing from the screen.
        const laid = fromElkGraph(CHAIN, { children: [{ id: 'parse', x: 10, y: 20 }] })
        expect(laid.nodes).toHaveLength(3)
        expect(laid.nodes[1]).toEqual({ id: 'active', x: 0, y: 0, width: NODE_WIDTH, height: NODE_HEIGHT })
    })

    test('carries the edges through as the pairs they join', () => {
        const laid = fromElkGraph(CHAIN, {})
        expect(laid.edges).toEqual([
            { id: 'parse->active', source: 'parse', target: 'active' },
            { id: 'active->report', source: 'active', target: 'report' },
        ])
    })
})

describe('placing a graph', () => {
    test('gives every node a position, and every edge its pair', async () => {
        const elk = rowEngine()
        const placed = await layoutDag(CHAIN, elk)

        expect(placed.nodes.map((one) => [one.id, one.x])).toEqual([
            ['parse', 0],
            ['active', 300],
            ['report', 600],
        ])
        expect(placed.edges).toHaveLength(2)
        expect(elk.seen).toHaveLength(1)
    })

    test('asks elk nothing about a graph with no nodes', async () => {
        const elk = rowEngine()
        expect(await layoutDag({ nodes: [], edges: [] }, elk)).toEqual({ nodes: [], edges: [] })
        expect(elk.seen).toHaveLength(0)
    })
})

describe('the size a placed node is drawn at', () => {
    const placed = { id: 'report', x: 300, y: 40, width: NODE_WIDTH, height: NODE_HEIGHT + STRIP_HEIGHT }

    test('is the size elk was told, which is the size the box is', () => {
        expect(drawnSize(placed)).toEqual({ width: NODE_WIDTH, height: NODE_HEIGHT + STRIP_HEIGHT })
    })

    test('is what a node states as its measurement, which is what keeps an edge on the canvas', () => {
        // REVERT-PROOF: React Flow throws away the handle bounds of a node object it has not
        // seen before unless the node states its own measurement, and it draws no edge at all
        // to a node with no bounds. A live run rebuilds every node object on every frame, so a
        // node handed over without this loses every edge that ends at it until it is measured
        // again -- which, on the last frame of a run, is never.
        expect(drawnSize(placed)).toEqual({ width: placed.width, height: placed.height })
    })
})

/** A chain of `n` steps, which is a shape `n` ranks deep. */
function chain(n: number): LayoutShape {
    const ids = Array.from({ length: n }, (_, index) => `s${String(index)}`)
    return {
        nodes: ids.map((id) => node(id)),
        edges: ids.slice(1).map((id, index): [string, string] => [`s${String(index)}`, id]),
    }
}

describe('how deep a shape is', () => {
    test('is the longest chain in it, not the count of its steps', () => {
        expect(rankDepth(CHAIN)).toBe(3)
        expect(rankDepth(chain(11))).toBe(11)
    })

    test('is the deepest branch where a shape has more than one', () => {
        expect(
            rankDepth({
                nodes: [node('parse'), node('left'), node('right'), node('report')],
                edges: [
                    ['parse', 'left'],
                    ['parse', 'right'],
                    ['left', 'report'],
                    ['right', 'report'],
                ],
            }),
        ).toBe(3)
    })

    test('is nothing for a shape with no steps, and one for steps that join nothing', () => {
        expect(rankDepth({ nodes: [], edges: [] })).toBe(0)
        expect(rankDepth({ nodes: [node('one'), node('two')], edges: [] })).toBe(1)
    })

    test('answers rather than hangs on a shape that closes a loop', () => {
        // The canvas refuses a loop and so does an apply, but a shape reduced from text
        // somebody is halfway through typing is not a promise.
        expect(
            rankDepth({
                nodes: [node('parse'), node('report')],
                edges: [
                    ['parse', 'report'],
                    ['report', 'parse'],
                ],
            }),
        ).toBeGreaterThan(0)
    })
})

describe('the options one shape is placed with', () => {
    test('are the layered ones for a shape a canvas can draw in one row', () => {
        expect(unwrappedWidth(chain(5))).toBeLessThanOrEqual(WRAP_WIDTH)
        expect(layoutOptionsFor(chain(5))).toEqual(LAYOUT_OPTIONS)
    })

    test('wrap the ranks onto rows for a shape too deep to read in one', () => {
        expect(unwrappedWidth(chain(11))).toBeGreaterThan(WRAP_WIDTH)
        expect(layoutOptionsFor(chain(11))).toEqual({ ...LAYOUT_OPTIONS, ...WRAP_OPTIONS })
    })

    test('measure a row as the nodes in it and the gaps between them', () => {
        expect(unwrappedWidth(chain(1))).toBe(NODE_WIDTH)
        expect(unwrappedWidth(chain(3))).toBe(3 * NODE_WIDTH + 2 * RANK_SPACING)
        expect(unwrappedWidth({ nodes: [], edges: [] })).toBe(0)
    })

    test('are what elk is handed', () => {
        expect(toElkGraph(chain(11)).layoutOptions).toEqual(layoutOptionsFor(chain(11)))
    })
})

describe('the zoom a fit settles at', () => {
    test('is held above the size a node stops being readable at', () => {
        // REVERT-PROOF: a fit answers a graph too big for the canvas by scaling it, and past
        // this a 14px title is grey lines. A big graph is panned to rather than shrunk.
        expect(fittedZoom(0.2)).toBe(FIT_MIN_ZOOM)
        expect(fitOptionsFor().minZoom).toBe(FIT_MIN_ZOOM)
    })

    test('is held below blowing a small graph up to fill the canvas', () => {
        expect(fittedZoom(4)).toBe(FIT_MAX_ZOOM)
        expect(fitOptionsFor().maxZoom).toBe(FIT_MAX_ZOOM)
    })

    test('is what the fit asked for when that is between the two', () => {
        expect(fittedZoom(0.9)).toBe(0.9)
    })
})

describe('one press of a zoom control', () => {
    test('is a step worth pressing in either direction', () => {
        expect(steppedZoom(1, 'in')).toBeGreaterThan(1.2)
        expect(steppedZoom(1, 'out')).toBeLessThan(0.85)
    })

    test('stops where the canvas stops', () => {
        expect(steppedZoom(MAX_ZOOM, 'in')).toBe(MAX_ZOOM)
        expect(steppedZoom(MIN_ZOOM, 'out')).toBe(MIN_ZOOM)
    })
})
