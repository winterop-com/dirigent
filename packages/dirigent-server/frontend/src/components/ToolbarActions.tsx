import { MoreHorizontal, type LucideIcon } from 'lucide-react'

import { Refusable } from '@/components/Refusable'
import { useSmallScreen } from '@/hooks/use-small-screen'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'

export const MORE_ACTIONS_LABEL = 'More actions'

/** One verb on a screen's strip, said once and drawn either as a button or as a menu row. */
export interface ToolbarAction {
    id: string
    label: string
    icon?: LucideIcon
    onClick: () => void
    disabled?: boolean
    /** Why the control is shut, which is what it says on hover and what `Refusable` carries. */
    why?: string
    variant?: 'default' | 'outline'
    /** The verb's full name, where the label alone does not say which noun. */
    ariaLabel?: string
    /** An action that takes something away, which says so under the pointer. */
    destructive?: boolean
}

/**
 * A screen's verbs: every one of them at `md` and up, the last one and a menu below it.
 *
 * A TOOLBAR DOES NOT WRAP. Three buttons beside a breadcrumb is a second line on a 390px
 * strip and a shell that reads as broken, so below the breakpoint the primary action -- the
 * last one, which is where the primary sits on the strip -- keeps its place and everything
 * else moves into one menu.
 *
 * The actions are data rather than markup because they are drawn twice, and a button and a
 * menu row that were written out separately are two labels that can disagree.
 */
export function ToolbarActions({ actions }: { actions: readonly ToolbarAction[] }) {
    const small = useSmallScreen()
    if (actions.length === 0) return null
    const primary = actions[actions.length - 1]
    const rest = actions.slice(0, -1)

    if (!small) {
        return (
            <div className="flex items-center gap-2">
                {actions.map((action) => (
                    <ActionButton key={action.id} action={action} />
                ))}
            </div>
        )
    }

    return (
        <>
            <div className="flex items-center gap-2">
                {rest.length > 0 && (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={<Button variant="ghost" size="icon-sm" aria-label={MORE_ACTIONS_LABEL} />}
                        >
                            <MoreHorizontal className="size-4" aria-hidden />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            {rest.map((action) => (
                                <DropdownMenuItem
                                    key={action.id}
                                    disabled={action.disabled}
                                    onClick={action.onClick}
                                    variant={action.destructive === true ? 'destructive' : 'default'}
                                >
                                    {action.icon !== undefined && <action.icon className="size-4" aria-hidden />}
                                    {action.label}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
                {primary !== undefined && <ActionButton action={primary} />}
            </div>
        </>
    )
}

function ActionButton({ action }: { action: ToolbarAction }) {
    const Icon = action.icon
    return (
        <Refusable why={action.why}>
            <Button
                variant={action.variant ?? 'outline'}
                size="sm"
                aria-label={action.ariaLabel}
                disabled={action.disabled}
                title={action.why}
                className={action.destructive === true ? 'destructive-action' : undefined}
                onClick={action.onClick}
            >
                {Icon !== undefined && <Icon aria-hidden />}
                {action.label}
            </Button>
        </Refusable>
    )
}
