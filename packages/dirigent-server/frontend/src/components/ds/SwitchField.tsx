import type { ReactNode } from 'react'

import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'

/**
 * A boolean setting as a row: the label and its help on the left, the switch on the right.
 *
 * The whole row is the label, so a press anywhere on it flips the switch. Shut with `why`, which
 * the row says on hover and which replaces the help while it is shut.
 */
export function SwitchField({
    id,
    label,
    help,
    checked,
    onCheckedChange,
    why,
    className,
}: {
    id: string
    label: string
    help?: ReactNode
    checked: boolean
    onCheckedChange: (checked: boolean) => void
    why?: string
    className?: string
}) {
    const shut = why !== undefined
    return (
        <label
            htmlFor={id}
            title={why}
            className={cn(
                'flex min-w-0 items-start justify-between gap-4 py-2',
                shut ? 'cursor-not-allowed' : 'cursor-pointer',
                className,
            )}
        >
            <span className="flex min-w-0 flex-col gap-0.5">
                <span className={cn('text-sm font-medium', shut && 'text-muted-foreground')}>{label}</span>
                {(shut || help !== undefined) && (
                    <span className="text-xs text-muted-foreground">{shut ? why : help}</span>
                )}
            </span>
            <Switch
                id={id}
                checked={checked}
                disabled={shut}
                className="mt-0.5 rounded-sm *:data-[slot=switch-thumb]:rounded-xs"
                onCheckedChange={(next) => {
                    onCheckedChange(next)
                }}
            />
        </label>
    )
}
