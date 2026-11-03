import { describe, expect, test } from 'vitest'

import {
    boxWidth,
    DEFAULT_LAYOUT,
    fromElkGraph,
    heightOf,
    LAYOUT_OPTIONS,
    layoutOptionsFor,
    measureByCharacters,
    NODE_CHROME,
    NODE_HEIGHT,
    NODE_MAX_WIDTH,
    NODE_MIN_WIDTH,
    placedByRank,
    routedPath,
    signatureOf,
    STRIP_HEIGHT,
    stripLines,
    toElkGraph,
    WHEEL_ZOOM_LIMIT,
    wheelZoomFactor,
    type LayoutShape,
} from '@/lib/dag-layout'
import { chipWidth, shapeNodeWidth } from '@/lib/node-size'
import { chosenStep, pipelineStepPath, queryForStep, queryWith, runStepPath } from '@/lib/step-address'

const FAN_IN: LayoutShape = {
    nodes: [
        { id: 'levels', height: NODE_HEIGHT },
        { id: 'jobs', height: NODE_HEIGHT },
        { id: 'health', height: NODE_HEIGHT },
    ],
    edges: [
        ['levels', 'health'],
        ['jobs', 'health'],
    ],
}

describe('a view laid out the default way', () => {
    test('is handed exactly the options every canvas has always opened on', () => {
        expect(layoutOptionsFor(FAN_IN)).toBe(LAYOUT_OPTIONS)
        expect(layoutOptionsFor(FAN_IN, DEFAULT_LAYOUT)).toBe(LAYOUT_OPTIONS)
    })
})

describe('a view a reader laid out another way', () => {
    test('runs top to bottom when asked', () => {
        const options = layoutOptionsFor(FAN_IN, { ...DEFAULT_LAYOUT, direction: 'down' })
        expect(options['elk.direction']).toBe('DOWN')
    })

    test('routes its edges around the boxes, each into its step on its own', () => {
        const options = layoutOptionsFor(FAN_IN, { ...DEFAULT_LAYOUT, routing: 'orthogonal' })
        expect(options['elk.edgeRouting']).toBe('ORTHOGONAL')
        expect(options['elk.layered.mergeEdges']).toBe('false')
        expect(Number(options['elk.spacing.edgeEdge'])).toBeGreaterThan(0)
        expect(Number(options['elk.spacing.edgeNode'])).toBeGreaterThan(0)
    })

    test('curves its edges when asked for splines', () => {
        expect(layoutOptionsFor(FAN_IN, { ...DEFAULT_LAYOUT, routing: 'splines' })['elk.edgeRouting']).toBe(
            'SPLINES',
        )
    })

    test('leaves more room between ranks when roomy than when compact', () => {
        const roomy = layoutOptionsFor(FAN_IN, { ...DEFAULT_LAYOUT, spacing: 'roomy' })
        const compact = layoutOptionsFor(FAN_IN, { ...DEFAULT_LAYOUT, spacing: 'compact' })
        const between = 'elk.layered.spacing.nodeNodeBetweenLayers'
        expect(Number(roomy[between])).toBeGreaterThan(Number(compact[between]))
    })

    test('is placed again, because the choice is part of what the placement is keyed on', () => {
        expect(signatureOf(FAN_IN, { ...DEFAULT_LAYOUT, direction: 'down' })).not.toBe(signatureOf(FAN_IN))
        expect(
            toElkGraph(FAN_IN, { ...DEFAULT_LAYOUT, direction: 'down' }).layoutOptions['elk.direction'],
        ).toBe('DOWN')
    })

    test('is drawn down the canvas before elk answers, one row per rank', () => {
        const placed = placedByRank(FAN_IN, { ...DEFAULT_LAYOUT, direction: 'down' })
        const at = new Map(placed.nodes.map((one) => [one.id, one]))
        expect(at.get('health')?.y).toBeGreaterThan(at.get('levels')?.y ?? 0)
        expect(at.get('jobs')?.y).toBe(at.get('levels')?.y)
    })
})

describe("elk's routes", () => {
    test('are read back as each edge’s points, start to end', () => {
        const placed = fromElkGraph(FAN_IN, {
            edges: [
                {
                    id: 'levels->health',
                    sections: [
                        {
                            startPoint: { x: 0, y: 0 },
                            bendPoints: [{ x: 10, y: 0 }],
                            endPoint: { x: 10, y: 20 },
                        },
                    ],
                },
            ],
        })
        expect(placed.edges.find((edge) => edge.id === 'levels->health')?.points).toEqual([
            { x: 0, y: 0 },
            { x: 10, y: 0 },
            { x: 10, y: 20 },
        ])
        expect(placed.edges.find((edge) => edge.id === 'jobs->health')?.points).toBeUndefined()
    })

    test('are drawn as straight runs turned on a small radius', () => {
        const path = routedPath(
            [
                { x: 0, y: 0 },
                { x: 20, y: 0 },
                { x: 20, y: 20 },
            ],
            false,
        )
        expect(path).toBe('M 0 0 L 14 0 Q 20 0 20 6 L 20 20')
    })

    test('are drawn as cubic segments when they are splines', () => {
        const points = [
            { x: 0, y: 0 },
            { x: 5, y: 0 },
            { x: 10, y: 5 },
            { x: 10, y: 10 },
        ]
        expect(routedPath(points, true)).toBe('M 0 0 C 5 0, 10 5, 10 10')
    })
})

describe('how wide a box is', () => {
    test('is its widest line and its chrome, between the floor and the cap', () => {
        expect(boxWidth([10])).toBe(NODE_MIN_WIDTH)
        expect(boxWidth([200])).toBe(200 + NODE_CHROME)
        expect(boxWidth([2000])).toBe(NODE_MAX_WIDTH)
    })

    test('holds a long step code whole', () => {
        const words = { title: 'data_elements_by_domain', named: false, line: 'transform.jq' }
        const width = shapeNodeWidth(words, false, true, measureByCharacters)
        expect(width - NODE_CHROME).toBeGreaterThanOrEqual(measureByCharacters(words.title, 'title-mono'))
    })
})

describe("a fan-out's chips", () => {
    test('wrap onto as many lines as the room asks, never fewer than one', () => {
        expect(stripLines([], 100)).toBe(1)
        expect(stripLines([40, 40], 100)).toBe(1)
        expect(stripLines([40, 40, 40], 100)).toBe(2)
    })

    test('make the box taller by a line each', () => {
        expect(heightOf(true, 3) - heightOf(true, 1)).toBe(2 * STRIP_HEIGHT)
    })

    test('reserve a retry at its widest, so a countdown moves no box', () => {
        const one = chipWidth({ key: 'tracker', retry: 'try 2 in 9s' }, measureByCharacters)
        const other = chipWidth({ key: 'tracker', retry: 'try 2 in 59s' }, measureByCharacters)
        expect(one).toBe(other)
    })
})

describe('a modified wheel over a canvas on a page', () => {
    test('zooms in on a pinch outward and out on one inward', () => {
        expect(wheelZoomFactor(-4)).toBeGreaterThan(1)
        expect(wheelZoomFactor(4)).toBeLessThan(1)
    })

    test('moves a mouse wheel notch one bounded step, not to the end of the range', () => {
        expect(wheelZoomFactor(-100)).toBe(WHEEL_ZOOM_LIMIT)
        expect(wheelZoomFactor(100)).toBe(1 / WHEEL_ZOOM_LIMIT)
        expect(wheelZoomFactor(-3, 1)).toBe(WHEEL_ZOOM_LIMIT)
    })
})

describe('a chosen step as an address', () => {
    test('is the run or the pipeline with the step after it', () => {
        expect(runStepPath('r-1', null)).toBe('/runs/r-1')
        expect(runStepPath('r-1', 'org_units_by_level')).toBe('/runs/r-1/org_units_by_level')
        expect(pipelineStepPath('health', 'jobs')).toBe('/pipelines/health/jobs')
    })

    test('keeps the tab and drops the element and the try of the step before', () => {
        expect(queryForStep('tab=report&item=i-1&attempt=a-1')).toBe('?tab=report')
        expect(queryForStep('item=i-1')).toBe('')
    })

    test('names an element or a try, and stops naming it', () => {
        expect(queryWith('tab=report', 'attempt', 'a-1')).toBe('?tab=report&attempt=a-1')
        expect(queryWith('attempt=a-1', 'attempt', null)).toBe('')
    })

    test('chooses a step the graph holds, and says so of one it does not', () => {
        expect(chosenStep('jobs', ['jobs'])).toEqual({ kind: 'step', code: 'jobs' })
        expect(chosenStep('nope', ['jobs'])).toEqual({ kind: 'unknown', code: 'nope' })
        expect(chosenStep(undefined, ['jobs'])).toEqual({ kind: 'none' })
        // While the graph is still being read nothing is called unknown.
        expect(chosenStep('nope', null)).toEqual({ kind: 'none' })
    })
})
