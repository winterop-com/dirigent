import { ReactFlowProvider } from '@xyflow/react'
import type { ReactNode } from 'react'

import { Panel } from '@/components/ds/Panel'
import { PageCanvasTools, type CanvasFrame } from '@/components/graph/GraphCanvas'
import { WindowedPane } from '@/components/WindowedPane'
import type { LayoutChoice } from '@/lib/dag-layout'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/**
 * A view of a graph on a page: the panel it stands in, the controls in that panel's bar, and the
 * same graph in a window.
 *
 * THE CONTROLS STAND IN THE BAR, NOT OVER THE DRAWING. A canvas on a page is as tall as what it
 * draws, so a cluster in its corner would sit on a box; the bar has the room. The layout they
 * choose is the caller's, held for the visit, and the window draws with the same one.
 *
 * THE WINDOW IS A STAGE. There the wheel zooms, as it does on any canvas that is the whole of
 * what is on screen, and its own corner carries the zoom and the layout. A box chosen in it is
 * chosen on the page as well, so closing the window leaves the reader where they were.
 */
export function GraphPanel({
    name,
    frame,
    layout,
    onLayout,
    canvas,
    className,
    children,
}: {
    /** What the window is titled and the window's button names. */
    name: string
    /** How the canvas on the page is sized: to its drawing, or to the room the page leaves it. */
    frame: Extract<CanvasFrame, 'fitted' | 'filled'>
    layout: LayoutChoice
    onLayout: (layout: LayoutChoice) => void
    /** The canvas, drawn once in each frame. */
    canvas: (frame: CanvasFrame) => ReactNode
    className?: string
    /** What stands under the canvas inside the panel. */
    children?: ReactNode
}) {
    const filled = frame === 'filled'
    return (
        <ReactFlowProvider>
            <Panel
                title={LABELS.pipelines.page.graph}
                tone="graph"
                inset={false}
                aside={<PageCanvasTools frame={frame} layout={layout} onLayout={onLayout} />}
                className={cn(filled && 'flex flex-1 flex-col', className)}
                bodyClassName={cn(filled && 'flex min-h-0 flex-1 flex-col')}
            >
                <WindowedPane
                    name={LABELS.shell.graph_window(name)}
                    frame="none"
                    className={cn(filled && 'flex-1')}
                    windowed={
                        <ReactFlowProvider>
                            <div className="relative min-h-0 flex-1" data-graph-window>
                                <div className="absolute inset-0">{canvas('window')}</div>
                            </div>
                        </ReactFlowProvider>
                    }
                >
                    {canvas(frame)}
                </WindowedPane>
                {children}
            </Panel>
        </ReactFlowProvider>
    )
}
