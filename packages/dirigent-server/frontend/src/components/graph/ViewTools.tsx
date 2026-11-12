import type { GraphControls } from '@winterop-com/sokkel-ui-graph/GraphCanvas'
import { GraphControlButton, GraphViewButtons } from '@winterop-com/sokkel-ui-graph/GraphViewButtons'
import { GraphLayoutMenu, type GraphLayoutChoice } from '@winterop-com/sokkel-ui-graph/GraphLayoutMenu'
import type { GraphRouting } from '@winterop-com/sokkel-ui-graph/layout'
import { IconButton } from '@winterop-com/sokkel-ui/IconButton'
import { GRAPH_LAYOUT_WORDS, GRAPH_WORDS } from '@/lib/design-system'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { applePlatform, modifierLabel } from '@/lib/shortcuts'

/** The edges a view's layout menu offers. */
const ROUTINGS: readonly GraphRouting[] = ['orthogonal', 'splines']

/**
 * The layout menu of a view of a graph, opened by the `Layout` button and closed by a choice. In
 * the head the button is an `IconButton`; in the window's cluster it is the cluster's own.
 */
export function LayoutButton({
    value,
    onValueChange,
    flush = false,
}: {
    value: GraphLayoutChoice
    onValueChange: (layout: GraphLayoutChoice) => void
    /** Drawn as a button of the window's flush cluster. */
    flush?: boolean
}) {
    return (
        <GraphLayoutMenu
            value={value}
            onValueChange={onValueChange}
            routings={ROUTINGS}
            words={GRAPH_LAYOUT_WORDS}
            closeOnChoice
            trigger={
                flush ? (
                    <GraphControlButton label={LABELS.shell.layout.menu}>
                        <ICONS.graph_layout aria-hidden />
                    </GraphControlButton>
                ) : (
                    <IconButton
                        label={LABELS.shell.layout.menu}
                        size="icon-sm"
                        className="text-muted-foreground"
                    >
                        <ICONS.graph_layout aria-hidden />
                    </IconButton>
                )
            }
        />
    )
}

/** What the zoom buttons' tooltips say on a page, by how the canvas stands there: how else it zooms. */
function zoomTips(frame: 'fitted' | 'filled'): { out: string; in: string } {
    if (frame === 'filled') return { out: LABELS.shell.zoom_out_filled, in: LABELS.shell.zoom_in_filled }
    const modifier = modifierLabel(applePlatform(navigator.userAgent))
    return { out: LABELS.shell.zoom_out_on_page(modifier), in: LABELS.shell.zoom_in_on_page(modifier) }
}

/**
 * Zoom in, zoom out and fit for the canvas that handed out `controls`, then the layout menu. A
 * canvas with nothing on it draws no zoom. In a page's head they are `IconButton`s whose tooltips
 * say how else the canvas zooms there; in the window's corner they are sokkel-ui-graph's flush
 * cluster, `GraphViewButtons`.
 */
export function ViewTools({
    controls,
    frame,
    layout,
    onLayout,
}: {
    controls: GraphControls | null
    frame: 'fitted' | 'filled' | 'window'
    layout: GraphLayoutChoice
    onLayout: (layout: GraphLayoutChoice) => void
}) {
    if (frame === 'window') {
        return (
            <GraphViewButtons controls={controls} whenEmpty="hide" words={GRAPH_WORDS}>
                <LayoutButton value={layout} onValueChange={onLayout} flush />
            </GraphViewButtons>
        )
    }
    const tips = zoomTips(frame)
    return (
        <span className="flex items-center gap-0.5 font-normal">
            {controls !== null && !controls.empty && (
                <>
                    <IconButton
                        label={LABELS.shell.zoom_in}
                        tooltip={tips.in}
                        size="icon-sm"
                        className="text-muted-foreground"
                        onClick={controls.zoomIn}
                    >
                        <ICONS.zoom_in aria-hidden />
                    </IconButton>
                    <IconButton
                        label={LABELS.shell.zoom_out}
                        tooltip={tips.out}
                        size="icon-sm"
                        className="text-muted-foreground"
                        onClick={controls.zoomOut}
                    >
                        <ICONS.zoom_out aria-hidden />
                    </IconButton>
                    <IconButton
                        label={LABELS.shell.fit_view}
                        size="icon-sm"
                        className="text-muted-foreground"
                        onClick={controls.fit}
                    >
                        <ICONS.fit_view aria-hidden />
                    </IconButton>
                </>
            )}
            <LayoutButton value={layout} onValueChange={onLayout} />
        </span>
    )
}
