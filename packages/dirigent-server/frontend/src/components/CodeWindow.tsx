import { useState } from 'react'

import { Maximize2 } from 'lucide-react'

import { CodePane } from '@/components/pipeline/CodePane'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'

/**
 * A window onto one piece of produced data: the full editor, read-only.
 *
 * A step's output is drawn inline in a small box because most outputs are small; the ones
 * that are not deserve the same surface source is edited in -- folding, search, syntax --
 * without ever becoming editable, because what a run produced is a fact.
 */
export function CodeWindow({
    title,
    text,
    mediaType,
    path,
}: {
    /** What the window is headed by: the step and which of its faces this is. */
    title: string
    text: string
    /** How the buffer is tokenised; JSON when the caller says so, YAML when nothing is said. */
    mediaType?: string
    /** The model this buffer is registered under, distinct per window. */
    path: string
}) {
    const [open, setOpen] = useState(false)
    return (
        <>
            <Button
                variant="ghost"
                size="icon"
                aria-label={`Open ${title} in a window`}
                className="absolute top-1.5 right-3.5 size-6 rounded-md border border-border bg-background/90 text-faint"
                onClick={() => {
                    setOpen(true)
                }}
            >
                <Maximize2 className="size-3.5" aria-hidden />
            </Button>
            <Dialog open={open} onOpenChange={setOpen}>
                {/* Focus is not handed back to the control on close: the library restores it
                    after the exit animation, past any blur, and the ring it then wears reads
                    as a selection nobody made. */}
                <DialogContent
                    finalFocus={false}
                    className="flex h-[85vh] w-[min(64rem,90vw)] max-w-[min(64rem,90vw)] flex-col gap-3 sm:max-w-[min(64rem,90vw)]"
                >
                    <DialogTitle className="font-mono text-sm">{title}</DialogTitle>
                    <CodePane
                        value={text}
                        mediaType={mediaType}
                        path={path}
                        label={title}
                        readOnly
                        className="min-h-0 flex-1"
                    />
                </DialogContent>
            </Dialog>
        </>
    )
}
