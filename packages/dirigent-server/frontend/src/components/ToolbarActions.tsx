import { MoreHorizontal, type LucideIcon } from 'lucide-react'
import { useCallback, useEffect, useLayoutEffect, useState } from 'react'

import { Refusable } from '@/components/Refusable'
import { useSmallScreen } from '@/hooks/use-small-screen'
import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { nextForm, TABLE, type Form } from '@/lib/card-form'
import { LABELS } from '@/lib/labels'

export const MORE_ACTIONS_LABEL = LABELS.shell.more_actions

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
 * A screen's verbs: every one of them where they fit, the last one and a menu where they do not.
 *
 * A TOOLBAR DOES NOT WRAP. Three buttons beside a breadcrumb is a second line on a 390px
 * strip and a shell that reads as broken, so below the breakpoint the primary action -- the
 * last one, which is where the primary sits on the strip -- keeps its place and everything
 * else moves into one menu.
 *
 * A `measured` toolbar folds the same way wherever its own box cannot hold every button, which
 * is how a page heading beside an open panel keeps its whole width: the box is what is left of
 * the strip, and the buttons are measured against it rather than squeezing what stands beside
 * it. It unfolds once it has the width the buttons took and `SLACK` more, so a strip dragged
 * across that edge does not strobe.
 *
 * The actions are data rather than markup because they are drawn twice, and a button and a
 * menu row that were written out separately are two labels that can disagree.
 */
export function ToolbarActions({
    actions,
    measured = false,
}: {
    actions: readonly ToolbarAction[]
    /** Fold whenever the buttons do not fit the room this toolbar is given, not only below `md`. */
    measured?: boolean
}) {
    const small = useSmallScreen()
    const [box, setBox] = useState<HTMLDivElement | null>(null)
    const [form, setForm] = useState<Form>(TABLE)

    const measure = useCallback(() => {
        const held = box?.firstElementChild
        if (!measured || box === null || !(held instanceof HTMLElement)) return
        const room = box.clientWidth
        const taken = Math.ceil(held.getBoundingClientRect().width)
        // The layout is the external thing this synchronizes with, and it cannot be read until
        // the DOM has been written: the fold is settled before the frame is painted.
        // oxlint-disable-next-line react/set-state-in-effect
        setForm((now) => nextForm(now, room, taken))
    }, [box, measured])

    useLayoutEffect(measure)

    useEffect(() => {
        if (box === null || !measured || typeof ResizeObserver === 'undefined') return
        const observer = new ResizeObserver(measure)
        observer.observe(box)
        return () => {
            observer.disconnect()
        }
    }, [box, measure, measured])

    if (actions.length === 0) return null
    const folded = small || (measured && form.cards)
    const primary = actions[actions.length - 1]
    const rest = actions.slice(0, -1)

    const strip = folded ? (
        <div className="flex shrink-0 items-center gap-2">
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
    ) : (
        <div className="flex shrink-0 items-center gap-2">
            {actions.map((action) => (
                <ActionButton key={action.id} action={action} />
            ))}
        </div>
    )

    if (!measured) return strip
    return (
        <div ref={setBox} className="flex min-w-0 flex-1 justify-end">
            {strip}
        </div>
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
