import type { ReactNode } from 'react'

import type { GraphControls } from '@winterop-com/sokkel-ui-graph/GraphCanvas'
import { GraphLayoutMenu, type GraphLayoutChoice } from '@winterop-com/sokkel-ui-graph/GraphLayoutMenu'
import type { GraphRouting } from '@winterop-com/sokkel-ui-graph/layout'
import { IconButton } from '@winterop-com/sokkel-ui/IconButton'
import { GRAPH_LAYOUT_WORDS } from '@/lib/design-system'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { applePlatform, modifierLabel } from '@/lib/shortcuts'

/** What a view of a graph opens on. */
export const GRAPH_LAYOUT: GraphLayoutChoice = {
    direction: 'right',
    routing: 'orthogonal',
    spacing: 'normal',
}

/** The least zoom a fit of a view goes to, at every width. */
export const FIT_MIN_ZOOM = 0.8

/** The least zoom a fit goes to when the drawing fits across and only its height is short. */
export const TALL_FIT = 0.7

/** The edges a view's layout menu offers. */
const ROUTINGS: readonly GraphRouting[] = ['orthogonal', 'splines']

/** The layout menu of a view of a graph, opened by the `Layout` button and closed by a choice. */
export function LayoutButton({
    value,
    onValueChange,
}: {
    value: GraphLayoutChoice
    onValueChange: (layout: GraphLayoutChoice) => void
}) {
    return (
        <GraphLayoutMenu
            value={value}
            onValueChange={onValueChange}
            routings={ROUTINGS}
            words={GRAPH_LAYOUT_WORDS}
            closeOnChoice
            trigger={
                <IconButton label={LABELS.shell.layout.menu} size="icon-sm" className="text-muted-foreground">
                    <ICONS.graph_layout aria-hidden />
                </IconButton>
            }
        />
    )
}

/** What the zoom buttons' tooltips add, by where the canvas stands: how else it zooms there. */
function zoomTips(frame: 'fitted' | 'filled' | 'window'): { out?: string; in?: string } {
    if (frame === 'filled') return { out: LABELS.shell.zoom_out_filled, in: LABELS.shell.zoom_in_filled }
    if (frame === 'window') return {}
    const modifier = modifierLabel(applePlatform(navigator.userAgent))
    return { out: LABELS.shell.zoom_out_on_page(modifier), in: LABELS.shell.zoom_in_on_page(modifier) }
}

/**
 * Zoom out, zoom in and fit for the canvas that handed out `controls`, then the layout menu. A
 * canvas with nothing on it draws no zoom. On a page the zoom buttons' tooltips say how else the
 * canvas zooms there.
 */
export function ViewTools({
    controls,
    frame,
    menu,
}: {
    controls: GraphControls | null
    frame: 'fitted' | 'filled' | 'window'
    menu: ReactNode
}) {
    const tips = zoomTips(frame)
    return (
        <span className="flex items-center gap-0.5 font-normal">
            {controls !== null && !controls.empty && (
                <>
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
                        label={LABELS.shell.zoom_in}
                        tooltip={tips.in}
                        size="icon-sm"
                        className="text-muted-foreground"
                        onClick={controls.zoomIn}
                    >
                        <ICONS.zoom_in aria-hidden />
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
            {menu}
        </span>
    )
}
