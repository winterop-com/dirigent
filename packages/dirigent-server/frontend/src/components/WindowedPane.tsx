import { useState, type ReactNode } from 'react'

import { CodeFrame } from '@/components/ds/CodeFrame'
import { IconButton } from '@/components/ds/IconButton'
import { Inset } from '@/components/ds/Inset'
import { ICONS } from '@/lib/icons'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
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
 * THE BUTTON SITS WHERE NO TEXT DOES, and this is the only place it is drawn: in a strip of its
 * own under the pane, at the bottom-right corner of the box. The pane scrolls above the strip, so
 * a line that runs to the right edge, wherever the pane is scrolled to, ends before the button
 * rather than under it. Every pane that offers a window -- a source field, a report document, an
 * alert body, a block of produced JSON -- takes the button, the corner and the window from here,
 * so there is one corner to learn.
 *
 * TWO EDITORS OVER ONE BUFFER READ THE SAME BUFFER. Monaco holds one model per path, so a
 * source pane and its window name the same one: what is typed in either is what the other
 * shows, and closing the window loses nothing. The caller hands over both panes for that
 * reason rather than this moving one.
 */
export function WindowedPane({
    name,
    frame = 'field',
    className,
    onBlur,
    children,
    windowed,
    aside,
    held,
}: {
    /** What the content is called: the window's title, and what the button names. */
    name: string
    /**
     * What the box around the pane and the button's strip is: a code editor's field, an inset
     * of reference material, or nothing where the pane fills a panel of its own.
     */
    frame?: 'field' | 'inset' | 'none'
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
     * For a pane that grows with its content: the button's strip is held to the foot of the
     * scroller the pane sits in, on that scroller's ground -- a panel's, or the right panel's.
     */
    held?: 'panel' | 'sidebar'
}) {
    const [wide, setWide] = useState(false)
    const inPlace = (
        <>
            <div className="flex min-h-0 flex-1 flex-col">{children}</div>
            <div
                className={cn(
                    'dg-window-strip flex shrink-0 justify-end p-1.5 pt-0',
                    held !== undefined && 'pt-1.5',
                    held === 'panel' && 'bg-panel-ground',
                    held === 'sidebar' && 'bg-sidebar',
                )}
                data-held={held}
            >
                <IconButton
                    icon={ICONS.open_in_window}
                    label={LABELS.shell.open_in_window(name)}
                    size="xs"
                    variant="outline"
                    className="text-faint"
                    onClick={() => {
                        setWide(true)
                    }}
                />
            </div>
        </>
    )
    return (
        <>
            {frame === 'field' ? (
                <CodeFrame className={className} onBlur={onBlur}>
                    {inPlace}
                </CodeFrame>
            ) : frame === 'inset' ? (
                <div onBlur={onBlur} className="contents">
                    <Inset className={cn('flex flex-col', className)}>{inPlace}</Inset>
                </div>
            ) : (
                <div className={cn('flex flex-col', className)} onBlur={onBlur}>
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
