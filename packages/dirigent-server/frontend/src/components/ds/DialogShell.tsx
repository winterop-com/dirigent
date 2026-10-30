import type { ReactNode } from 'react'

import { Refusable } from '@/components/Refusable'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { DIALOG_WIDTHS, type DialogWidth } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/** The forward path of a dialog that asks. */
export interface DialogConfirm {
    label: string
    onConfirm: () => void
    /** Why the confirm is shut; it stays drawn and says this on hover. */
    why?: string
    /** A write in flight: the confirm is shut and says `busyLabel`. */
    busy?: boolean
    busyLabel?: string
    /** A confirm that takes something away, drawn in the critical fill. */
    destructive?: boolean
}

/**
 * Every dialog's frame: one of four widths, a title, an optional description, a body that
 * scrolls under a fixed header and footer, and the surface capped at the window.
 *
 * A dialog that asks passes `confirm`, and its footer is `Cancel` and the confirm, with no
 * corner close. A dialog that only tells passes none: it has no footer, and is dismissed by the
 * corner close and Escape. `Cancel` is the only dismissal word a footer says. A dialog that reads
 * one thing passes `verbs`: the corner close, and a footer of what can be done to that thing.
 */
export function DialogShell({
    open,
    onOpenChange,
    width = 'md',
    title,
    description,
    confirm,
    footer,
    verbs,
    keepOnOutsidePress = false,
    children,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    width?: DialogWidth
    title: ReactNode
    description?: ReactNode
    confirm?: DialogConfirm
    /** Anything the footer carries at its start, opposite the verbs. */
    footer?: ReactNode
    /**
     * What a dialog that reads one thing offers on it, in place of a confirm. The corner close
     * stays, because nothing has been started that a Cancel would take back.
     */
    verbs?: ReactNode
    /** A press outside does nothing, for a dialog holding a form somebody is typing in. */
    keepOnOutsidePress?: boolean
    children?: ReactNode
}) {
    const shut = confirm?.why !== undefined || confirm?.busy === true
    return (
        <Dialog open={open} onOpenChange={onOpenChange} disablePointerDismissal={keepOnOutsidePress}>
            <DialogContent
                className={cn('flex max-h-[calc(100vh-4rem)] flex-col', DIALOG_WIDTHS[width])}
                showCloseButton={confirm === undefined}
            >
                <DialogHeader className={confirm === undefined ? 'pr-8' : undefined}>
                    <DialogTitle className="leading-6">{title}</DialogTitle>
                    {description !== undefined && <DialogDescription>{description}</DialogDescription>}
                </DialogHeader>
                {children !== undefined && (
                    <div className="-mx-4 min-h-0 flex-1 space-y-4 overflow-y-auto px-4">{children}</div>
                )}
                {confirm !== undefined && (
                    <DialogFooter className="items-center">
                        {footer !== undefined && <div className="mr-auto min-w-0">{footer}</div>}
                        <DialogClose render={<Button variant="ghost" />}>{LABELS.action.cancel}</DialogClose>
                        <Refusable why={confirm.why}>
                            <Button
                                aria-disabled={shut || undefined}
                                title={confirm.why}
                                className={cn(
                                    confirm.destructive === true && 'confirm-destructive',
                                    shut && 'cursor-not-allowed opacity-50',
                                )}
                                onClick={shut ? undefined : confirm.onConfirm}
                            >
                                {confirm.busy === true ? (confirm.busyLabel ?? confirm.label) : confirm.label}
                            </Button>
                        </Refusable>
                    </DialogFooter>
                )}
                {confirm === undefined && verbs !== undefined && (
                    <DialogFooter className="items-center">
                        {footer !== undefined && <div className="mr-auto min-w-0">{footer}</div>}
                        {verbs}
                    </DialogFooter>
                )}
            </DialogContent>
        </Dialog>
    )
}
