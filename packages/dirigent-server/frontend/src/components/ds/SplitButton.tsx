import { Refusable } from '@/components/Refusable'
import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ICONS, type Icon } from '@/lib/icons'
import { cn } from '@/lib/utils'

/** One other way to do what a split button's face does. */
export interface SplitItem {
    id: string
    label: string
    icon?: Icon
    onClick: () => void
}

/**
 * A primary verb with its other ways beside it: the face does the common one, the chevron
 * opens the rest. Both halves are shut together by `why`, which each says on hover.
 */
export function SplitButton({
    label,
    ariaLabel,
    icon: Glyph,
    onClick,
    more,
    moreLabel,
    why,
    variant = 'default',
}: {
    label: string
    /** The verb's full name, where `label` alone does not say which noun. */
    ariaLabel?: string
    icon?: Icon
    onClick: () => void
    more: readonly SplitItem[]
    /** What the chevron is called: "More ways to create a pipeline". */
    moreLabel: string
    why?: string
    variant?: 'default' | 'outline'
}) {
    const shut = why !== undefined
    const off = shut && 'cursor-not-allowed opacity-50'
    return (
        <Refusable why={why}>
            <div className="flex">
                <Button
                    size="sm"
                    variant={variant}
                    className={cn('rounded-r-none', off)}
                    aria-label={ariaLabel}
                    aria-disabled={shut || undefined}
                    title={why ?? ariaLabel}
                    onClick={shut ? undefined : onClick}
                >
                    {Glyph !== undefined && <Glyph aria-hidden />}
                    {label}
                </Button>
                <DropdownMenu>
                    <DropdownMenuTrigger
                        disabled={shut}
                        render={
                            <Button
                                size="sm"
                                variant={variant}
                                className={cn(
                                    'rounded-l-none border-l px-1.5',
                                    variant === 'default'
                                        ? 'border-primary-foreground/20'
                                        : 'border-l-border',
                                    off,
                                )}
                                aria-label={moreLabel}
                                title={why ?? moreLabel}
                            />
                        }
                    >
                        <ICONS.split aria-hidden />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        {more.map((item) => (
                            <DropdownMenuItem key={item.id} onClick={item.onClick}>
                                {item.icon !== undefined && <item.icon aria-hidden />}
                                {item.label}
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        </Refusable>
    )
}
