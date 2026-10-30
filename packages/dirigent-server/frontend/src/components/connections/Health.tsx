import { ToneDot } from '@/components/ds/ToneDot'
import type { HealthView } from '@/lib/connections'

/**
 * A credential's health, as every screen says it: a bare dot when it is healthy, and the dot and
 * the word when it failed or nothing was proved. The check's own sentence is the tooltip.
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
    return (
        <ToneDot
            tone={view.tone ?? 'unknown'}
            label={view.label}
            tip={view.detail}
            focusable={focusable}
            className={className}
        />
    )
}
