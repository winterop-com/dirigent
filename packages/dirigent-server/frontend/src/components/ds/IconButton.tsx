import type { ComponentProps } from 'react'

import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { iconButtonTip } from '@/lib/design-system'
import type { Icon } from '@/lib/icons'
import { cn } from '@/lib/utils'

/** What an icon button takes. `label` is required: an icon alone is a control with no name. */
export interface IconButtonProps extends Omit<
    ComponentProps<typeof Button>,
    'children' | 'aria-label' | 'title' | 'size' | 'variant'
> {
    icon: Icon
    /** The control's name: its `aria-label`, and its tooltip unless `tooltip` says more. */
    label: string
    /** A longer sentence for the tooltip, where the name alone does not say what happens. */
    tooltip?: string
    /** The key that does the same, drawn as a key cap in the tooltip. */
    shortcut?: string
    /** Why the control is shut. It stays focusable and hoverable, and its tooltip says this. */
    why?: string
    size?: 'sm' | 'md'
    variant?: 'ghost' | 'outline'
    /** A control that takes something away, which tints critical under the pointer. */
    destructive?: boolean
}

const SIZES = { sm: 'icon-sm', md: 'icon' } as const

/**
 * A button that is an icon and nothing else, with a name and a tooltip it cannot be drawn without.
 *
 * Shut with `why` rather than `disabled`: `aria-disabled` keeps it in the tab order and under
 * the pointer, the click is swallowed, and the tooltip says why.
 */
export function IconButton({
    icon: Glyph,
    label,
    tooltip,
    shortcut,
    why,
    size = 'md',
    variant = 'ghost',
    destructive = false,
    className,
    onClick,
    ...props
}: IconButtonProps) {
    const shut = why !== undefined
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <Button
                        {...props}
                        variant={variant}
                        size={SIZES[size]}
                        aria-label={label}
                        aria-disabled={shut || undefined}
                        className={cn(
                            destructive && 'destructive-action',
                            shut && 'cursor-not-allowed opacity-50 hover:bg-transparent',
                            className,
                        )}
                        onClick={shut ? undefined : onClick}
                    />
                }
            >
                <Glyph className={size === 'sm' ? 'size-3.5' : 'size-4'} aria-hidden />
            </TooltipTrigger>
            <TooltipContent>
                {iconButtonTip({ label, tooltip, why })}
                {shortcut !== undefined && !shut && <Kbd>{shortcut}</Kbd>}
            </TooltipContent>
        </Tooltip>
    )
}
