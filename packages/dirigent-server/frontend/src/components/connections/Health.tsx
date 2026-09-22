import type { CSSProperties } from 'react'

import type { HealthView } from '@/lib/connections'
import { cn } from '@/lib/utils'

/** What a dot is filled with. The aliases are index.css's, for what is not a run. */
const FILL: Record<'good' | 'critical', string> = { good: 'var(--good)', critical: 'var(--critical)' }

/** Three colours and no more: green where the check passed, red where it failed, grey otherwise. */
function fillOf(tone: HealthView['tone']): string {
    return tone === null ? 'var(--faint)' : FILL[tone]
}

/**
 * A credential's health, as the dot and the one word every screen says it in.
 *
 * The sentence the check itself wrote is not here: a row has no room for it, and where there is
 * room -- the connection's own page, the tooltip on its row -- it is drawn beside this.
 */
export function HealthSaid({ view, className }: { view: HealthView; className?: string }) {
    return (
        <span className={cn('flex items-center gap-2 text-xs', className)}>
            <span
                className="status-dot"
                style={{ '--chip': fillOf(view.tone) } as CSSProperties}
                aria-hidden
            />
            <span className={cn('whitespace-nowrap', view.tone === null && 'text-faint')}>{view.label}</span>
        </span>
    )
}
