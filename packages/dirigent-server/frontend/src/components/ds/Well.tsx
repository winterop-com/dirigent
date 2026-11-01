import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * A group that belongs together inside a surface: a form opened under its row, a minted secret,
 * a sample. The panel ground, a hairline edge, and inset 8px.
 *
 * It says nothing about how anything is going; a box that does is a `Notice`. How it is drawn is
 * `.dg-well` in `index.css`.
 */
export function Well({ children, className }: { children: ReactNode; className?: string }) {
    return <div className={cn('dg-well p-2', className)}>{children}</div>
}
