import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** Which rung a surface stands on. */
export type SurfaceTone = 'raised' | 'recessed' | 'critical'

/**
 * A surface on a page: a listing, a panel, a card.
 *
 * How a surface is drawn -- its ground, its corner, its elevation or its edge -- is `.dg-surface`
 * in `index.css` keyed by `data-tone`, and nothing else in the app spells it, so a treatment
 * changes in one place. A raised one stands off the page, a recessed one sits a rung below it,
 * and a critical one is the failure's wash. `inset` is false where the surface's own rows lay
 * out their padding, as a listing's do.
 */
export function Surface({
    tone = 'raised',
    inset = true,
    as: Tag = 'section',
    className,
    children,
    ...rest
}: {
    tone?: SurfaceTone
    inset?: boolean
    as?: 'section' | 'div'
    className?: string
    children: ReactNode
    'aria-label'?: string
    'aria-labelledby'?: string
}) {
    return (
        <Tag
            className={cn('dg-surface min-w-0 overflow-hidden', inset && 'p-4', className)}
            data-tone={tone}
            {...rest}
        >
            {children}
        </Tag>
    )
}
