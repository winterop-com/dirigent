import type { ReactNode } from 'react'

import { Section } from '@winterop-com/sokkel-ui/Section'
import { WindowedPane, WindowedPaneButton } from '@winterop-com/sokkel-ui/WindowedPane'
import { windowWords } from '@/lib/library-words'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/** Where a canvas is drawn: on the page, sized to its drawing or to the room left it, or in the window. */
export type CanvasFrame = 'fitted' | 'filled' | 'window'

/**
 * A view of a graph on a page: the panel it stands in, the controls in that panel's bar, and the
 * same graph in a window.
 *
 * THE CONTROLS STAND IN THE BAR, NOT OVER THE DRAWING. A canvas on a page is as tall as what it
 * draws, so a cluster in its corner would sit on a box; the bar has the room. The canvas carries
 * its own zoom and hands it out: `tools` are the bar's controls, and `windowTools` stand over the
 * window's top right corner. The canvas sizes the panel's body itself, to its drawing when fitted
 * and to its floor when filled.
 *
 * THE WINDOW IS A STAGE. There the wheel zooms, as it does on any canvas that is the whole of
 * what is on screen, and its own corner carries the zoom and the layout. A box chosen in it is
 * chosen on the page as well, so closing the window leaves the reader where they were.
 */
export function GraphPanel({
    name,
    frame,
    canvas,
    tools,
    windowTools,
    className,
    children,
}: {
    /** What the window is titled and the window's button names. */
    name: string
    /** How the canvas on the page is sized: to its drawing, or to the room the page leaves it. */
    frame: Exclude<CanvasFrame, 'window'>
    /** The canvas, drawn once in each frame. */
    canvas: (frame: CanvasFrame) => ReactNode
    /** The bar's controls. */
    tools: ReactNode
    /** What stands over the window's corner. */
    windowTools?: ReactNode
    className?: string
    /** What stands under the canvas inside the panel. */
    children?: ReactNode
}) {
    const filled = frame === 'filled'
    const windowName = LABELS.shell.graph_window(name)
    return (
        <WindowedPane
            title={windowName}
            keepPane
            button="none"
            className={cn(filled ? 'flex flex-1 flex-col' : 'shrink-0', className)}
            words={windowWords(windowName)}
        >
            {(where) =>
                where === 'pane' ? (
                    <Section
                        title={LABELS.pipelines.page.graph}
                        tone="graph"
                        flush
                        actions={
                            <span className="flex items-center gap-0.5">
                                {tools}
                                <WindowedPaneButton size="icon-sm" className="text-muted-foreground" />
                            </span>
                        }
                        className={cn(filled && 'flex min-h-0 flex-1 flex-col')}
                        bodyClassName={cn(filled && 'flex min-h-0 flex-1 flex-col')}
                    >
                        <div className={cn('relative min-w-0', filled && 'flex-1')}>{canvas(frame)}</div>
                        {children}
                    </Section>
                ) : (
                    <div className="relative min-h-0 flex-1" data-graph-window>
                        <div className="absolute inset-0">{canvas('window')}</div>
                        {windowTools !== undefined && (
                            <div className="absolute top-2 right-2">{windowTools}</div>
                        )}
                    </div>
                )
            }
        </WindowedPane>
    )
}
