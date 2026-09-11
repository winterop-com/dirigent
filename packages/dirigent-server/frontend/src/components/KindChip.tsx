import type { CSSProperties } from 'react'

import { kindLabel, kindTokens } from '@/lib/kinds'
import { cn } from '@/lib/utils'

/**
 * One kind, drawn the one way this app draws a kind.
 *
 * The fill rule is `.kind-chip` in index.css and the hue is the family `lib/kinds` puts the
 * kind in, so a connection kind in a listing row and the same kind in a panel cannot drift
 * apart. Nothing here decides a colour.
 */
export function KindChip({ kind, className }: { kind: string; className?: string }) {
    return (
        <span
            className={cn('kind-chip', className)}
            data-kind={kind}
            style={kindTokens(kind) as CSSProperties}
        >
            {kindLabel(kind)}
        </span>
    )
}
