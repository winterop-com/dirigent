/**
 * Where the boxes are, once somebody has moved one.
 *
 * ELK PLACES A GRAPH; A READER PLACES A BOX. `lib/dag-layout` is the layered geometry a document
 * gets the first time it is drawn, and it stays the answer for every step nobody has dragged. A
 * step that was dragged has an answer of its own, and it is that one -- otherwise the next
 * re-layout would undo the arrangement somebody made to read their own pipeline.
 *
 * PX-INTENT, PER PIPELINE, exactly as the right panel's width is. What somebody dragged a box to
 * was a decision about that pipeline's shape, so it is kept as the flow coordinates it was
 * dropped at, under `dirigent.layout.{pipeline}`, and survives a reload. Re-layout is how it is
 * given back: the stored positions go and elk decides again.
 *
 * It is a module store because the canvas draws it and the screen adding a step writes to it,
 * and neither is inside the other. `lib/store` imports no React, so all of this runs in Node.
 */

import type { PlacedNode } from '@/lib/dag-layout'
import { createStore } from '@/lib/store'

/** Every stored layout is one key under this, so a pipeline's own is found by its code. */
export const LAYOUT_KEY_PREFIX = 'dirigent.layout.'

/** Where one pipeline's dragged positions are kept. */
export function layoutKey(pipeline: string): string {
    return `${LAYOUT_KEY_PREFIX}${pipeline}`
}

/** Where one box was dropped, in flow coordinates. */
export interface Placement {
    x: number
    y: number
}

/** Every box somebody has moved, by the step it draws. */
export type Placements = Record<string, Placement>

/** One pipeline's arrangement, held for as long as its editor is open. */
export interface HeldLayout {
    /** The pipeline the placements are of, or null before one has been loaded. */
    pipeline: string | null
    placements: Placements
}

const NOTHING: HeldLayout = { pipeline: null, placements: {} }

export const heldLayout = createStore<HeldLayout>(NOTHING)

/**
 * What storage holds for one pipeline.
 *
 * Anything that is not a pair of finite numbers is dropped rather than drawn: a stored layout is
 * a convenience, and a box placed at NaN is a box nobody can find.
 */
export function readPlacements(pipeline: string): Placements {
    let stored: string | null = null
    try {
        stored = localStorage.getItem(layoutKey(pipeline))
    } catch {
        return {}
    }
    if (stored === null) return {}
    let parsed: unknown
    try {
        parsed = JSON.parse(stored) as unknown
    } catch {
        return {}
    }
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    const held: Placements = {}
    for (const [id, value] of Object.entries(parsed as Record<string, unknown>)) {
        const at = value as { x?: unknown; y?: unknown } | null
        if (at === null || typeof at !== 'object') continue
        if (typeof at.x !== 'number' || typeof at.y !== 'number') continue
        if (!Number.isFinite(at.x) || !Number.isFinite(at.y)) continue
        held[id] = { x: at.x, y: at.y }
    }
    return held
}

/** Keep one pipeline's arrangement between visits, or forget it when there is none left. */
export function writePlacements(pipeline: string, placements: Placements): void {
    try {
        if (Object.keys(placements).length === 0) localStorage.removeItem(layoutKey(pipeline))
        else localStorage.setItem(layoutKey(pipeline), JSON.stringify(placements))
    } catch {
        // Storage denied: the arrangement holds for as long as this document is open.
    }
}

/** Take one pipeline's stored arrangement as the one being drawn. */
export function loadPlacements(pipeline: string): void {
    heldLayout.set({ pipeline, placements: readPlacements(pipeline) })
}

/** Hold where a box is being dragged to. Storage is not written until the drag ends. */
export function holdPlacement(id: string, at: Placement): void {
    heldLayout.update((held) => ({ ...held, placements: { ...held.placements, [id]: at } }))
}

/** Keep what is held, which is what the end of a drag is. */
export function keepPlacements(): void {
    const held = heldLayout.get()
    if (held.pipeline === null) return
    writePlacements(held.pipeline, held.placements)
}

/** Put one step where it was asked for and keep it there, such as a step added at a drop point. */
export function placeStep(id: string, at: Placement): void {
    holdPlacement(id, at)
    keepPlacements()
}

/** Give the layout back to elk: every dragged position goes, here and in storage. */
export function forgetPlacements(): void {
    const held = heldLayout.get()
    if (held.pipeline !== null) writePlacements(held.pipeline, {})
    heldLayout.set({ pipeline: held.pipeline, placements: {} })
}

/**
 * elk's placement, overruled by what somebody dragged.
 *
 * A STEP NOBODY HAS MOVED KEEPS ELK'S SUGGESTION, which is what makes a step added to an
 * arranged canvas land somewhere sensible instead of at the origin.
 */
export function withHeld(placed: readonly PlacedNode[], placements: Placements): PlacedNode[] {
    return placed.map((node) => {
        const at = placements[node.id]
        return at === undefined ? node : { ...node, x: at.x, y: at.y }
    })
}
