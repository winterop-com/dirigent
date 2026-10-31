import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** Which rung a surface stands on. */
export type SurfaceTone = 'raised' | 'recessed' | 'critical'

const TONES: Record<SurfaceTone, string> = {
    raised: 'bg-card shadow-surface',
    recessed: 'bg-canvas',
    critical: 'bg-critical-wash',
}

/**
 * A surface on a page: a listing, a panel, a card.
 *
 * A raised one is lifted off the page by its shadow rather than edged, a recessed one sits a rung
 * below the page, and a critical one is the failure's wash. `inset` is false where the surface's
 * own rows lay out their padding, as a listing's do.
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
            className={cn('min-w-0 overflow-hidden rounded-lg', TONES[tone], inset && 'p-4', className)}
            {...rest}
        >
            {children}
        </Tag>
    )
}
