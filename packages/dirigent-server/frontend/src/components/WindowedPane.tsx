import { Maximize2 } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { cn } from '@/lib/utils'

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
 * THE BUTTON SITS WHERE NO TEXT DOES. The bottom-right corner of a pane is where its two
 * scrollbars meet and a document's last line ends early, so the button there covers nothing a
 * reader needs; at the top right it covered the tail of a program's first line.
 *
 * TWO EDITORS OVER ONE BUFFER READ THE SAME BUFFER. Monaco holds one model per path, so a
 * source pane and its window name the same one: what is typed in either is what the other
 * shows, and closing the window loses nothing. The caller hands over both panes for that
 * reason rather than this moving one.
 */
export function WindowedPane({
    name,
    className,
    onBlur,
    children,
    windowed,
    aside,
}: {
    /** What the content is called: the window's title, and what the button names. */
    name: string
    /** What the box around the pane in place is, which a source pane draws as a bordered field. */
    className?: string
    onBlur?: () => void
    /** The pane as it stands in place, at whatever height its caller gave it. */
    children: ReactNode
    /** The same buffer's pane, as the window draws it. */
    windowed: ReactNode
    /** What sits beside the pane in the window: a reference for what is being written. */
    aside?: ReactNode
}) {
    const [wide, setWide] = useState(false)
    return (
        <div className={cn('relative', className)} onBlur={onBlur}>
            {children}
            <Button
                variant="ghost"
                size="icon"
                aria-label={`Open ${name} in a window`}
                className="absolute right-3.5 bottom-1.5 size-6 rounded-md border border-border bg-background/90 text-faint"
                onClick={() => {
                    setWide(true)
                }}
            >
                <Maximize2 className="size-3.5" aria-hidden />
            </Button>
            <Dialog open={wide} onOpenChange={setWide}>
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
        </div>
    )
}
