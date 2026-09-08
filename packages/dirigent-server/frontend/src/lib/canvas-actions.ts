/**
 * The editor canvas's two verbs, as signals the palette can fire from outside the canvas.
 *
 * The menu and the layout live inside the React Flow provider; the palette lives in the
 * shell. A counter store is the smallest bridge: firing bumps it, the canvas effect answers
 * once per bump, and nothing holds a ref across the boundary.
 */

import { createStore } from '@/lib/store'

/** Bumped when somebody asks for the add-step menu without pointing at the canvas. */
export const addStepAsked = createStore(0)

export function askAddStep(): void {
    addStepAsked.set(addStepAsked.get() + 1)
}

/** Bumped when somebody asks for the boxes to go back where elk places them. */
export const relayoutAsked = createStore(0)

export function askRelayout(): void {
    relayoutAsked.set(relayoutAsked.get() + 1)
}
