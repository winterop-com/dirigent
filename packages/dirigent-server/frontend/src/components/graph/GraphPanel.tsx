import { ReactFlowProvider } from '@xyflow/react'
import type { ReactNode } from 'react'

import { Section } from '@winterop-com/sokkel-ui/Section'
import { WindowedPane, WindowedPaneButton } from '@winterop-com/sokkel-ui/WindowedPane'
import { PageCanvasTools, type CanvasFrame } from '@/components/graph/GraphCanvas'
import type { LayoutChoice } from '@/lib/dag-layout'
import { windowWords } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/**
 * A view of a graph on a page: the panel it stands in, the controls in that panel's bar, and the
 * same graph in a window.
 *
 * THE CONTROLS STAND IN THE BAR, NOT OVER THE DRAWING. A canvas on a page is as tall as what it
 * draws, so a cluster in its corner would sit on a box; the bar has the room. The layout they
 * choose is the caller's, held for the visit, and the window draws with the same one. A canvas
 * that carries its own zoom passes `tools` for the bar instead, and `windowTools` for the window,
 * which stand over the window's top right corner; filled, such a canvas sizes the panel's body to
 * its own floor.
 *
 * THE WINDOW IS A STAGE. There the wheel zooms, as it does on any canvas that is the whole of
 * what is on screen, and its own corner carries the zoom and the layout. A box chosen in it is
 * chosen on the page as well, so closing the window leaves the reader where they were.
 */
export function GraphPanel({
    name,
    frame,
    canvas,
    className,
    children,
    ...bar
}: {
    /** What the window is titled and the window's button names. */
    name: string
    /** How the canvas on the page is sized: to its drawing, or to the room the page leaves it. */
    frame: Extract<CanvasFrame, 'fitted' | 'filled'>
    /** The canvas, drawn once in each frame. */
    canvas: (frame: CanvasFrame) => ReactNode
    className?: string
    /** What stands under the canvas inside the panel. */
    children?: ReactNode
} & (
    | { layout: LayoutChoice; onLayout: (layout: LayoutChoice) => void }
    | {
          /** The bar's controls, for a canvas that carries its own zoom. */
          tools: ReactNode
          /** What stands over the window's corner. */
          windowTools?: ReactNode
      }
)) {
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
                    <ReactFlowProvider>
                        <Section
                            title={LABELS.pipelines.page.graph}
                            tone="graph"
                            flush
                            actions={
                                <span className="flex items-center gap-0.5">
                                    {'tools' in bar ? (
                                        bar.tools
                                    ) : (
                                        <PageCanvasTools
                                            frame={frame}
                                            layout={bar.layout}
                                            onLayout={bar.onLayout}
                                        />
                                    )}
                                    <WindowedPaneButton size="icon-sm" className="text-muted-foreground" />
                                </span>
                            }
                            className={cn(filled && 'flex min-h-0 flex-1 flex-col')}
                            bodyClassName={cn(filled && 'flex min-h-0 flex-1 flex-col')}
                        >
                            {'tools' in bar ? (
                                <div className={cn('relative min-w-0', filled ? 'flex-1' : 'h-60')}>
                                    {canvas(frame)}
                                </div>
                            ) : (
                                <div className={cn('flex min-w-0 flex-col', filled && 'min-h-0 flex-1')}>
                                    {canvas(frame)}
                                </div>
                            )}
                            {children}
                        </Section>
                    </ReactFlowProvider>
                ) : (
                    <ReactFlowProvider>
                        <div className="relative min-h-0 flex-1" data-graph-window>
                            <div className="absolute inset-0">{canvas('window')}</div>
                            {'tools' in bar && bar.windowTools !== undefined && (
                                <div className="absolute top-2 right-2 rounded-control border border-border bg-card p-0.5 shadow-node">
                                    {bar.windowTools}
                                </div>
                            )}
                        </div>
                    </ReactFlowProvider>
                )
            }
        </WindowedPane>
    )
}
