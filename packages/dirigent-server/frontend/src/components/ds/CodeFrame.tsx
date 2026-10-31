import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * A code editor drawn as the field it is: the field's ground, the input's edge, the control's
 * corner. `WindowedPane` draws every pane that opens in a window inside one.
 *
 * How it is drawn is `.dg-frame` in `index.css`; `className` sizes it.
 */
export function CodeFrame({
    children,
    className,
    onBlur,
}: {
    children: ReactNode
    className?: string
    onBlur?: () => void
}) {
    return (
        <div className={cn('dg-frame flex flex-col', className)} onBlur={onBlur}>
            {children}
        </div>
    )
}
