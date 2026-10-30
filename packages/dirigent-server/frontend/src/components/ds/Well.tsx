import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * A neutral inset box inside a surface: one rung up the ladder, edged, and inset 8px.
 *
 * It holds a block that belongs together -- a minted secret, a sample, a preview -- and says
 * nothing about how it is going; a box that does is a `Notice`.
 */
export function Well({ children, className }: { children: ReactNode; className?: string }) {
    return (
        <div className={cn('min-w-0 rounded-md border border-border bg-secondary/40 p-2', className)}>
            {children}
        </div>
    )
}
