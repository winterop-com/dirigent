/**
 * Work that is worth doing, but not worth doing now.
 *
 * `requestIdleCallback` is the only scheduler that says "when the browser has nothing else to
 * do". Every screen this app draws matters more than warming a chunk somebody may never open,
 * so anything speculative is handed here and the browser decides when.
 *
 * A BROWSER WITHOUT ONE GETS A TIMER. It is not the same promise -- a timer fires whether the
 * main thread is busy or not -- but it is late enough to be after first paint, which is the
 * property that matters here.
 */

/** How long after the call the fallback timer runs, and how long an idle callback may wait. */
const LATER_MS = 2000

/** What a browser that has one offers. */
type Idle = (task: () => void, options?: { timeout: number }) => void

/** Run a task once the browser is idle, or shortly after it where there is no idle to wait for. */
export function whenIdle(task: () => void): void {
    const idle = (globalThis as { requestIdleCallback?: Idle }).requestIdleCallback
    if (idle === undefined) {
        setTimeout(task, LATER_MS)
        return
    }
    idle(task, { timeout: LATER_MS })
}
