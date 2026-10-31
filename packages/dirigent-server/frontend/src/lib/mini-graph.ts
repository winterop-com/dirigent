/**
 * A pipeline's shape at the scale of a row: where each box of a miniature graph stands and which
 * edges it draws.
 *
 * Ranks are the longest path to a step, read left to right, and a rank's steps stack down, each
 * as near the row of what it waits for as the rank allows. An edge another path already implies
 * is left out, because a step that waits for everything before it would otherwise draw a fan of
 * lines and the shape would read as a tangle.
 */

/** One step as a miniature draws it: the wire's `StepShape`, narrowed to what is drawn. */
export interface MiniStep {
    code: string
    name: string | null
    kind: string
    block: string
    depends_on: string[]
    fan_out: boolean
}

/** One box, placed on the miniature's grid. */
export interface MiniBox {
    code: string
    /** What the box says on hover: its key, and the block it runs or what a source listens to. */
    label: string
    x: number
    y: number
    source: boolean
    fanOut: boolean
    failed: boolean
}

/** One edge, as the path an SVG draws. */
export interface MiniEdge {
    id: string
    d: string
}

/** A whole miniature, at its natural size. */
export interface MiniLayout {
    boxes: MiniBox[]
    edges: MiniEdge[]
    width: number
    height: number
}

/** How wide one box is drawn. */
export const MINI_BOX_WIDTH = 14
/** How tall one box is drawn. */
export const MINI_BOX_HEIGHT = 10
/** How far apart two ranks stand, which is the shared scale every miniature is drawn at. */
export const MINI_RANK_PITCH = 22
/** How far apart two boxes of one rank stand. */
export const MINI_ROW_PITCH = 14
/** How round an edge's corner is. */
const CORNER = 2

/** The longest path to every step, over the dependencies the shape itself carries. */
function ranksOf(steps: readonly MiniStep[]): Map<string, number> {
    const known = new Map(steps.map((step) => [step.code, step]))
    const ranks = new Map<string, number>()
    const rankOf = (code: string, path: ReadonlySet<string>): number => {
        const held = ranks.get(code)
        if (held !== undefined) return held
        if (path.has(code)) return 0
        const onward = new Set([...path, code])
        const before = (known.get(code)?.depends_on ?? []).filter((dependency) => known.has(dependency))
        const rank = before.reduce((most, dependency) => Math.max(most, rankOf(dependency, onward) + 1), 0)
        ranks.set(code, rank)
        return rank
    }
    for (const step of steps) rankOf(step.code, new Set())
    return ranks
}

/**
 * The dependencies that change the shape: every pair except those another path already implies.
 *
 * `[from, to]` is kept unless `to` can be reached from `from` through some other step.
 */
export function reducedEdges(steps: readonly MiniStep[]): [string, string][] {
    const known = new Set(steps.map((step) => step.code))
    const after = new Map<string, string[]>()
    const pairs: [string, string][] = []
    for (const step of steps) {
        for (const dependency of step.depends_on) {
            if (!known.has(dependency) || dependency === step.code) continue
            after.set(dependency, [...(after.get(dependency) ?? []), step.code])
            pairs.push([dependency, step.code])
        }
    }
    const reaches = (from: string, to: string, skipping: string): boolean => {
        const seen = new Set<string>()
        const stack = (after.get(from) ?? []).filter((next) => next !== skipping)
        while (stack.length > 0) {
            const next = stack.pop()
            if (next === undefined || seen.has(next)) continue
            if (next === to) return true
            seen.add(next)
            stack.push(...(after.get(next) ?? []))
        }
        return false
    }
    return pairs.filter(([from, to]) => !reaches(from, to, to))
}

/** The path one edge draws, from the right of one box to the left of the other. */
function edgePath(from: MiniBox, to: MiniBox): string {
    const startX = from.x + MINI_BOX_WIDTH
    const startY = from.y + MINI_BOX_HEIGHT / 2
    const endX = to.x
    const endY = to.y + MINI_BOX_HEIGHT / 2
    if (startY === endY) return `M${String(startX)} ${String(startY)}L${String(endX)} ${String(endY)}`
    const turn = endX - (MINI_RANK_PITCH - MINI_BOX_WIDTH) / 2
    const down = endY > startY ? 1 : -1
    return [
        `M${String(startX)} ${String(startY)}`,
        `L${String(turn - CORNER)} ${String(startY)}`,
        `Q${String(turn)} ${String(startY)} ${String(turn)} ${String(startY + down * CORNER)}`,
        `L${String(turn)} ${String(endY - down * CORNER)}`,
        `Q${String(turn)} ${String(endY)} ${String(turn + CORNER)} ${String(endY)}`,
        `L${String(endX)} ${String(endY)}`,
    ].join('')
}

/** Place a pipeline's steps on the miniature's grid, with the step a run failed in marked. */
export function miniLayout(steps: readonly MiniStep[], failed: string | null = null): MiniLayout {
    if (steps.length === 0) return { boxes: [], edges: [], width: 0, height: 0 }
    const ranks = ranksOf(steps)
    const edges = reducedEdges(steps)
    const before = new Map<string, string[]>()
    for (const [from, to] of edges) before.set(to, [...(before.get(to) ?? []), from])

    const rows = new Map<string, number>()
    const depth = Math.max(...ranks.values()) + 1
    let tallest = 0
    for (let rank = 0; rank < depth; rank += 1) {
        const here = steps
            .map((step, index) => ({ step, index }))
            .filter(({ step }) => ranks.get(step.code) === rank)
            .map(({ step, index }) => {
                const wanted = (before.get(step.code) ?? []).map((from) => rows.get(from) ?? 0)
                return { step, index, wanted: wanted.length === 0 ? 0 : Math.min(...wanted) }
            })
            .toSorted((one, other) => one.wanted - other.wanted || one.index - other.index)
        let next = 0
        for (const { step, wanted } of here) {
            const row = Math.max(wanted, next)
            rows.set(step.code, row)
            next = row + 1
            tallest = Math.max(tallest, row)
        }
    }

    const boxes = steps.map((step) => ({
        code: step.code,
        label: `${step.code} · ${step.block}`,
        x: (ranks.get(step.code) ?? 0) * MINI_RANK_PITCH,
        y: (rows.get(step.code) ?? 0) * MINI_ROW_PITCH,
        source: step.kind === 'source',
        fanOut: step.fan_out,
        failed: step.code === failed,
    }))
    const byCode = new Map(boxes.map((box) => [box.code, box]))
    return {
        boxes,
        edges: edges.flatMap(([from, to]) => {
            const start = byCode.get(from)
            const end = byCode.get(to)
            return start === undefined || end === undefined ? [] : [{ id: `${from}->${to}`, d: edgePath(start, end) }]
        }),
        width: (depth - 1) * MINI_RANK_PITCH + MINI_BOX_WIDTH,
        height: tallest * MINI_ROW_PITCH + MINI_BOX_HEIGHT,
    }
}

/** How much a miniature is shrunk to stand inside a lead cell, never enlarged. */
export function miniScale(layout: Pick<MiniLayout, 'width' | 'height'>, room: { width: number; height: number }): number {
    if (layout.width === 0 || layout.height === 0) return 1
    return Math.min(1, room.width / layout.width, room.height / layout.height)
}
