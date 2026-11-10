import { Dot } from '@winterop-com/sokkel-ui/Dot'

import { dotOf } from '@/lib/design-system'
import { cn } from '@/lib/utils'
import type { HealthView } from '@/lib/connections'

/**
 * A credential's health, as every screen says it: a bare dot when it is healthy, and the dot and
 * the word when it failed or nothing was proved. The check's own sentence is the tooltip, under the
 * word where the dot does not say it.
 */
export function HealthSaid({
    view,
    focusable,
    className,
}: {
    view: HealthView
    /** Put the tooltip in the tab order, where nothing around the dot is a control. */
    focusable?: boolean
    className?: string
}) {
    const dot = dotOf({ tone: view.tone ?? 'unknown', label: view.label })
    const detail = view.detail === null || view.detail === '' ? null : view.detail
    const tip =
        detail === null ? (
            dot.tip
        ) : dot.say === true ? (
            detail
        ) : (
            <span className="flex flex-col items-start gap-1">
                <span>{view.label}</span>
                <span className="opacity-70">{detail}</span>
            </span>
        )
    return <Dot {...dot} tip={tip} focusable={focusable} className={cn(dot.className, className)} />
}
