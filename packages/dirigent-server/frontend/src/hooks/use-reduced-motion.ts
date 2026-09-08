import { useSyncExternalStore } from 'react'

/** What the operating system's setting is asked as. */
const QUERY = '(prefers-reduced-motion: reduce)'

function query(): MediaQueryList | null {
    return typeof window.matchMedia === 'function' ? window.matchMedia(QUERY) : null
}

function subscribe(changed: () => void): () => void {
    const media = query()
    media?.addEventListener('change', changed)
    return () => {
        media?.removeEventListener('change', changed)
    }
}

/**
 * Whether somebody has asked their machine for less motion.
 *
 * A COMPONENT DECIDES WITH THIS, RATHER THAN A STYLESHEET DECIDING BEHIND IT. What moves on
 * this app's graph is which classes an edge is given, and a media query that quietly stopped an
 * animation would leave the class saying one thing and the screen showing another. The setting
 * is answered here and the classes follow it; index.css stops the animations as well, so a
 * frame drawn before a change lands is still still.
 */
export function usePrefersReducedMotion(): boolean {
    return useSyncExternalStore(
        subscribe,
        () => query()?.matches ?? false,
        () => false,
    )
}
