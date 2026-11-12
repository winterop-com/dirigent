import type { GraphControls } from '@winterop-com/sokkel-ui-graph/GraphCanvas'
import {
    GraphControlButton,
    GraphViewButtons,
    type GraphViewWords,
} from '@winterop-com/sokkel-ui-graph/GraphViewButtons'
import { GraphLayoutMenu, type GraphLayoutChoice } from '@winterop-com/sokkel-ui-graph/GraphLayoutMenu'
import type { GraphRouting } from '@winterop-com/sokkel-ui-graph/layout'
import { GRAPH_LAYOUT_WORDS, GRAPH_WORDS } from '@/lib/design-system'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { applePlatform, modifierLabel } from '@/lib/shortcuts'

/** The edges a view's layout menu offers. */
const ROUTINGS: readonly GraphRouting[] = ['orthogonal', 'splines']

/** What the zoom buttons' tooltips say, by where the canvas stands: how else it zooms there. */
function zoomHints(frame: 'fitted' | 'filled' | 'window'): Partial<GraphViewWords> {
    if (frame === 'window') return {}
    if (frame === 'filled') {
        return { zoomInHint: LABELS.shell.zoom_in_filled, zoomOutHint: LABELS.shell.zoom_out_filled }
    }
    const modifier = modifierLabel(applePlatform(navigator.userAgent))
    return {
        zoomInHint: LABELS.shell.zoom_in_on_page(modifier),
        zoomOutHint: LABELS.shell.zoom_out_on_page(modifier),
    }
}

/**
 * Zoom in, zoom out and fit for the canvas that handed out `controls`, then the layout menu, as
 * sokkel-ui-graph's flush cluster, in a page's bar and in the window's corner alike. A canvas with
 * nothing on it draws no zoom. On a page the zoom buttons' tooltips say how else the canvas zooms
 * there.
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
    return (
        <GraphViewButtons
            controls={controls}
            whenEmpty="hide"
            words={{ ...GRAPH_WORDS, ...zoomHints(frame) }}
        >
            <GraphLayoutMenu
                value={layout}
                onValueChange={onLayout}
                routings={ROUTINGS}
                words={GRAPH_LAYOUT_WORDS}
                closeOnChoice
                trigger={
                    <GraphControlButton label={LABELS.shell.layout.menu}>
                        <ICONS.graph_layout aria-hidden />
                    </GraphControlButton>
                }
            />
        </GraphViewButtons>
    )
}
