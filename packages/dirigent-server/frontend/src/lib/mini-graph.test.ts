import { describe, expect, it } from 'vitest'

import {
    MINI_RANK_PITCH,
    MINI_ROW_PITCH,
    miniLayout,
    miniScale,
    reducedEdges,
    type MiniStep,
} from './mini-graph'

const step = (code: string, depends_on: string[] = [], extra: Partial<MiniStep> = {}): MiniStep => ({
    code,
    name: null,
    kind: 'block',
    block: 'transform.jq',
    depends_on,
    fan_out: false,
    ...extra,
})

describe('reducedEdges', () => {
    it('leaves out an edge another path already implies', () => {
        const steps = [step('a'), step('b', ['a']), step('c', ['a', 'b'])]
        expect(reducedEdges(steps)).toEqual([
            ['a', 'b'],
            ['b', 'c'],
        ])
    })

    it('keeps every edge of a shape with no shortcut in it', () => {
        const steps = [step('a'), step('b', ['a']), step('c', ['a'])]
        expect(reducedEdges(steps)).toEqual([
            ['a', 'b'],
            ['a', 'c'],
        ])
    })

    it('ignores a dependency the shape does not carry', () => {
        expect(reducedEdges([step('a', ['gone'])])).toEqual([])
    })
})

describe('miniLayout', () => {
    it('lays a chain out along one row at the shared pitch', () => {
        const layout = miniLayout([step('a'), step('b', ['a']), step('c', ['b'])])
        expect(layout.boxes.map((box) => [box.x, box.y])).toEqual([
            [0, 0],
            [MINI_RANK_PITCH, 0],
            [2 * MINI_RANK_PITCH, 0],
        ])
        expect(layout.width).toBe(2 * MINI_RANK_PITCH + 14)
        expect(layout.height).toBe(10)
    })

    it('stacks a rank down and keeps a step near the row of what it waits for', () => {
        const layout = miniLayout([step('a'), step('b', ['a']), step('k', ['a']), step('z', ['k'])])
        const at = new Map(layout.boxes.map((box) => [box.code, box.y]))
        expect(at.get('b')).toBe(0)
        expect(at.get('k')).toBe(MINI_ROW_PITCH)
        expect(at.get('z')).toBe(MINI_ROW_PITCH)
    })

    it('marks a source, a fan-out and the step a run failed in', () => {
        const layout = miniLayout(
            [step('in', [], { kind: 'source', block: 'sensor' }), step('each', ['in'], { fan_out: true })],
            'each',
        )
        expect(layout.boxes.map((box) => [box.source, box.fanOut, box.failed])).toEqual([
            [true, false, false],
            [false, true, true],
        ])
        expect(layout.boxes[0]?.label).toBe('in · sensor')
    })

    it('draws nothing for a pipeline with no version', () => {
        expect(miniLayout([])).toEqual({ boxes: [], edges: [], width: 0, height: 0 })
    })
})

describe('miniScale', () => {
    it('never enlarges and shrinks to the tighter of the two bounds', () => {
        expect(miniScale({ width: 50, height: 10 }, { width: 200, height: 40 })).toBe(1)
        expect(miniScale({ width: 400, height: 10 }, { width: 200, height: 40 })).toBe(0.5)
        expect(miniScale({ width: 100, height: 80 }, { width: 200, height: 40 })).toBe(0.5)
    })
})
