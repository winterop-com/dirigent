import type { ReactNode } from 'react'

/**
 * A shut control that says why, on the element around it.
 *
 * A disabled control takes no pointer events, so a `title` on the button itself is a sentence
 * nobody can reach. The wrapper is what the pointer lands on, and a control that is not shut is
 * left as it stands rather than wrapped in a span that says nothing.
 */
export function Refusable({ why, children }: { why: string | undefined; children: ReactNode }) {
    if (why === undefined) return children
    return <span title={why}>{children}</span>
}
