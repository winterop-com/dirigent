/**
 * The trail the top bar draws: the screens above the one in front of somebody, each a link.
 *
 * The bar is the shell's and is drawn once; the trail is the screen's, stated for as long as it
 * is mounted. A listing states none.
 */

import type { Crumb } from '@winterop-com/sokkel-ui/TopBar'

import { createStore } from '@/lib/store'

export type { Crumb }

const NONE: readonly Crumb[] = []

export const screenTrail = createStore<readonly Crumb[]>(NONE)

/** Whether two trails say the same steps to the same places. */
export function sameTrail(a: readonly Crumb[], b: readonly Crumb[]): boolean {
    return (
        a.length === b.length &&
        a.every((crumb, index) => {
            const other = b[index]
            return crumb.label === other.label && crumb.href === other.href && crumb.code === other.code
        })
    )
}

/** State this screen's trail. Publishes nothing when it is the trail already drawn. */
export function setScreenTrail(next: readonly Crumb[]): void {
    if (sameTrail(screenTrail.get(), next)) return
    screenTrail.set(next)
}

/** State no trail, which is what a screen leaving the shell does. */
export function clearScreenTrail(): void {
    screenTrail.set(NONE)
}
