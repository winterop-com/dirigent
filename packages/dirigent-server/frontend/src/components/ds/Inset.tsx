import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * Reference material inside a surface: a block of JSON, a code block in a description, a log.
 * The page's own ground and a hairline edge, so it reads as cut into what it stands on.
 *
 * How it is drawn is `.dg-inset` in `index.css`; `className` lays out what is inside it.
 */
export function Inset({ children, className }: { children: ReactNode; className?: string }) {
    return <div className={cn('dg-inset', className)}>{children}</div>
}
