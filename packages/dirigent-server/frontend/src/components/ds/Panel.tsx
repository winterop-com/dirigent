import { useId, type ReactNode } from 'react'

import { ICONS } from '@/lib/icons'
import { cn } from '@/lib/utils'

/** What a panel holds: an ordinary section, a graph on its dot grid, or a failure. */
export type PanelTone = 'plain' | 'graph' | 'critical'

/**
 * A section of a page: a title bar with its label at the left and a count or a fact at the
 * right, a hairline under the bar, and a body on a ground of its own.
 *
 * How a panel is drawn is `.dg-panel` in `index.css`, keyed by `data-tone`, and nothing else in
 * the app spells it, so a treatment changes in one place. A failure carries a rule in the failed
 * ink along its top and the warning mark beside its title. `inset` is false where the body's own
 * rows lay out their padding, as a listing's do.
 */
export function Panel({
    title,
    meta,
    aside,
    tone = 'plain',
    inset = true,
    className,
    bodyClassName,
    children,
}: {
    title: ReactNode
    /** The count or fact the bar says at its right, in mono. */
    meta?: ReactNode
    /** A control or link the bar carries after the meta. */
    aside?: ReactNode
    tone?: PanelTone
    inset?: boolean
    className?: string
    bodyClassName?: string
    children: ReactNode
}) {
    const id = useId()
    return (
        <section className={cn('dg-panel min-w-0', className)} data-tone={tone} aria-labelledby={id}>
            <div className="dg-panel-head">
                <h2 id={id} className="flex min-w-0 items-center gap-2 truncate">
                    {tone === 'critical' && <ICONS.warning className="size-4 shrink-0" aria-hidden />}
                    {title}
                </h2>
                {(meta !== undefined || aside !== undefined) && (
                    <span className="flex shrink-0 items-center gap-3">
                        {meta !== undefined && (
                            <span className="font-mono text-xs font-normal text-muted-foreground">
                                {meta}
                            </span>
                        )}
                        {aside}
                    </span>
                )}
            </div>
            <div className={cn('dg-panel-body', inset && 'p-4', bodyClassName)}>{children}</div>
        </section>
    )
}
