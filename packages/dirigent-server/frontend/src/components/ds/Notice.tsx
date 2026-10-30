import type { ReactNode } from 'react'

import { ICONS, type Icon } from '@/lib/icons'
import { cn } from '@/lib/utils'

/** How much a notice matters: a failure, a caution, or a plain fact the reader should see. */
export type NoticeTone = 'critical' | 'warning' | 'neutral'

const TONES: Record<NoticeTone, { box: string; ink: string; icon: Icon }> = {
    critical: { box: 'border-critical/35 bg-critical/8', ink: 'text-critical-ink', icon: ICONS.critical },
    warning: { box: 'border-warning/35 bg-warning/8', ink: 'text-warning-ink', icon: ICONS.warning },
    neutral: { box: 'border-border bg-secondary/40', ink: 'text-muted-foreground', icon: ICONS.info },
}

/**
 * A sentence the reader must not miss, in a box edged in its tone and inset 8px.
 *
 * The tone's own mark leads unless `icon={false}`; `title` is a bold first line. A refusal off
 * the wire is `Refusal`, not this.
 */
export function Notice({
    tone = 'neutral',
    title,
    icon = true,
    children,
    className,
}: {
    tone?: NoticeTone
    title?: string
    icon?: boolean
    children?: ReactNode
    className?: string
}) {
    const look = TONES[tone]
    const Mark = look.icon
    return (
        <div
            role={tone === 'critical' ? 'alert' : 'status'}
            className={cn(
                'flex min-w-0 items-start gap-2 rounded-md border p-2 text-sm',
                look.box,
                className,
            )}
        >
            {icon && <Mark className={cn('mt-0.5 size-4 shrink-0', look.ink)} aria-hidden />}
            <div className="min-w-0 space-y-0.5 break-words">
                {title !== undefined && <p className="font-medium">{title}</p>}
                {children !== undefined && <div className="text-muted-foreground">{children}</div>}
            </div>
        </div>
    )
}
