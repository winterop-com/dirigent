import ELK from 'elkjs/lib/elk-api.js'
import ElkWorker from 'elkjs/lib/elk-worker.min.js?worker'

import type { ElkEngine } from '@/lib/dag-layout'

/**
 * elk itself, in a worker of its own.
 *
 * IT IS LOADED IN ITS OWN CHUNK. Nothing imports this file by name: `use-placed` beside it is
 * the one dynamic import, and every canvas reaches the engine through it.
 *
 * THE ALGORITHM IS NOT ON THE THREAD THAT DRAWS. `elk-api` is the small half of elkjs, a
 * promise wrapper around a worker; `elk-worker.min.js` is the algorithm, fetched and parsed by
 * the worker when it starts. Placing a fifty-step graph is then work the canvas is not blocked
 * on, and a tab that opens no canvas fetches neither half.
 */
export function newElk(): ElkEngine {
    return new ELK({ workerFactory: () => new ElkWorker() })
}
