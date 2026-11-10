import { useState, type ReactNode } from 'react'

import { IconButton } from '@winterop-com/sokkel-ui/IconButton'
import { Inset } from '@/components/ds/Inset'
import { ICONS } from '@/lib/icons'
import { Dialog, DialogContent, DialogTitle } from '@winterop-com/sokkel-ui/primitives/dialog'
import { cn } from '@/lib/utils'
import { LABELS } from '@/lib/labels'

/**
 * A pane in its box, and the same content in a window as large as the screen allows.
 *
 * WHAT IS IN THE PANEL IS TALLER AND WIDER THAN THE PANEL. A template written in a box the
 * height of a form row is read four lines at a time, and a run's report document is a page of
 * prose and a table in a column 360px wide -- so every pane holding one offers the window, and
 * the button is the whole of that gesture.
 *
 * THE WINDOW IS THE VIEWPORT. A program's window is where the whole program is read, so it
 * takes all the screen there is, less a gutter; a reference for the language sits beside the
 * editor when the caller has one, and stacks below it on a narrow screen.
 *
 * THE BUTTON IS AT THE TOP, WHERE THE EYE STARTS. A pane in a panel with a head hands its
 * button to the head, beside the panel's other tools: the caller draws `WindowButton` in the
 * head, holds `open`, and passes `button="none"`. A pane with no head keeps the button inside its
 * own top-right corner, in a row of no height held to the top of whatever scrolls it, so it stays
 * on screen down a long document and covers no more than the end of the first line. This is the
 * only place the gesture is written, so there is one corner to learn.
 *
 * THE WINDOW DRAWS ITS OWN VIEW. The pane stays in place while the window is open, so the caller
 * hands over both; two code editors over one buffer are two views of one shared document.
 */
/** The button that opens a pane's window, for a panel head to stand beside its other tools. */
export function WindowButton({ name, onOpen }: { name: string; onOpen: () => void }) {
    return (
        <IconButton
            label={LABELS.shell.open_in_window(name)}
            size="icon-sm"
            className="text-muted-foreground"
            onClick={onOpen}
        >
            <ICONS.open_in_window aria-hidden />
        </IconButton>
    )
}

export function WindowedPane({
    name,
    frame = 'none',
    className,
    onBlur,
    children,
    windowed,
    aside,
    held,
    button = 'corner',
    open,
    onOpenChange,
}: {
    /** What the content is called: the window's title, and what the button names. */
    name: string
    /**
     * What the box around the pane is: an inset of reference material, or nothing, where the pane
     * draws its own box or fills a panel of its own.
     */
    frame?: 'inset' | 'none'
    /** How the box is sized and laid out. */
    className?: string
    onBlur?: () => void
    /** The pane as it stands in place, at whatever height its caller gave it. */
    children: ReactNode
    /** The same buffer's pane, as the window draws it. */
    windowed: ReactNode
    /** What sits beside the pane in the window: a reference for what is being written. */
    aside?: ReactNode
    /**
     * For a pane that grows with its content: the button is held to the top of the scroller the
     * pane sits in, on that scroller's ground -- a panel's, or the right panel's.
     */
    held?: 'panel' | 'sidebar'
    /** Where the button is: the pane's own top-right corner, or nowhere, where a head draws it. */
    button?: 'corner' | 'none'
    /** Whether the window is open, for a caller whose head holds the button. */
    open?: boolean
    onOpenChange?: (open: boolean) => void
}) {
    const [own, setOwn] = useState(false)
    const wide = open ?? own
    const setWide = onOpenChange ?? setOwn
    const inPlace = (
        <>
            {button === 'corner' && (
                <div
                    className={cn(
                        'dg-window-corner pointer-events-none sticky top-0 z-10 flex h-0 justify-end overflow-visible',
                        held === undefined ? 'pr-5' : 'pr-2',
                    )}
                    data-held={held}
                >
                    <IconButton
                        label={LABELS.shell.open_in_window(name)}
                        size="icon-xs"
                        variant="outline"
                        className={cn(
                            'pointer-events-auto mt-1.5 text-faint',
                            held === 'panel' && 'bg-panel-ground',
                            held === 'sidebar' && 'bg-sidebar',
                        )}
                        onClick={() => {
                            setWide(true)
                        }}
                    >
                        <ICONS.open_in_window aria-hidden />
                    </IconButton>
                </div>
            )}
            <div className="flex min-h-0 flex-1 flex-col">{children}</div>
        </>
    )
    return (
        <>
            {frame === 'inset' ? (
                <div onBlur={onBlur} className="contents">
                    <Inset className={cn('flex flex-col', className)}>{inPlace}</Inset>
                </div>
            ) : (
                <div className={cn('flex min-w-0 flex-col', className)} onBlur={onBlur}>
                    {inPlace}
                </div>
            )}
            <Dialog open={wide} onOpenChange={setWide}>
                {/* Focus is not handed back to the control on close: the library restores it
                    after the exit animation, past any blur, and the ring it then wears reads
                    as a selection nobody made. */}
                <DialogContent
                    finalFocus={false}
                    className="flex h-[calc(100vh-2rem)] w-[calc(100vw-2rem)] max-w-none flex-col gap-3 sm:max-w-none"
                >
                    <DialogTitle className="font-mono text-sm">{name}</DialogTitle>
                    <div className="flex min-h-0 flex-1 flex-col gap-4 md:flex-row">
                        <div className="flex min-h-0 min-w-0 flex-1 flex-col">{windowed}</div>
                        {aside !== undefined && (
                            <aside className="max-h-48 shrink-0 overflow-y-auto border-t border-border pt-3 md:max-h-none md:w-80 md:border-t-0 md:border-l md:pt-0 md:pl-4">
                                {aside}
                            </aside>
                        )}
                    </div>
                </DialogContent>
            </Dialog>
        </>
    )
}
