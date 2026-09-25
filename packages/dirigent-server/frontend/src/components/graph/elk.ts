import type { ElkEngine } from '@/lib/dag-layout'
import { whenIdle } from '@/lib/idle'

/**
 * The one door to elk, which every canvas reaches the engine through.
 *
 * ONE DYNAMIC IMPORT, ONE CHUNK. elk is larger than the rest of this bundle, so it is fetched
 * when a canvas first asks for a layout rather than with the graph screens, and the one worker
 * it starts serves every canvas for the life of the tab.
 *
 * IT IS WARMED WHILE NOBODY IS WAITING. `warmLayout` is that same import, fired once the
 * browser is idle, so the first canvas of a session is placed against a worker already running.
 * A warm that fails costs nothing: the next canvas asks again.
 *
 * NOTHING HERE IS REACT, and nothing it imports is elk: the shell holds this module to warm the
 * chunk, so what the entry carries is the ask and not the engine.
 */
const load = () => import('@/components/graph/elk-engine')

/** The engine this tab is placing with, or null until a canvas has asked for one. */
let engine: Promise<ElkEngine> | null = null

/** Whether the chunk has already been asked for, because asking twice warms nothing. */
let warmed = false

/** elk, fetched on the first ask and held for the life of the tab. */
export function elkEngine(): Promise<ElkEngine> {
    engine ??= load()
        .then((module) => module.newElk())
        .catch((reason: unknown) => {
            // A chunk that never arrived is asked for again by the next canvas.
            engine = null
            throw reason
        })
    return engine
}

/** Fetch elk's chunk and start its worker while the browser has nothing better to do. */
export function warmLayout(): void {
    if (warmed) return
    warmed = true
    whenIdle(() => {
        void elkEngine().catch(() => undefined)
    })
}
