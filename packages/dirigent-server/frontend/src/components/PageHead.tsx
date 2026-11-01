import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { useStore } from '@/hooks/use-store'
import { createStore } from '@/lib/store'

/** Where a page's head is drawn: the shell's slot above the scroller, set once the shell mounts. */
export const headSlot = createStore<HTMLElement | null>(null)

/**
 * A page's head -- its title, its code, its line of facts and its verbs -- drawn above the page's
 * scroller, so it stands still while the body scrolls. `inPlace` draws it where it is rendered,
 * which is what the design system's gallery does.
 */
export function PageHead({ children, inPlace = false }: { children: ReactNode; inPlace?: boolean }) {
    const slot = useStore(headSlot)
    if (inPlace) return <>{children}</>
    return slot === null ? null : createPortal(children, slot)
}
