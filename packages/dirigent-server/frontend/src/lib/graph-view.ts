import type { GraphLayoutChoice } from '@winterop-com/sokkel-ui-graph/GraphLayoutMenu'

/** What a view of a graph opens on. */
export const GRAPH_LAYOUT: GraphLayoutChoice = {
    direction: 'right',
    routing: 'orthogonal',
    spacing: 'normal',
}

/**
 * The least zoom a fit goes to: a 13px title stays at 10.4px and an 11px word at 8.8px. A graph
 * too big to fit at it is shown at it and panned to; on a canvas narrower than 560px a view's fit
 * goes lower to fit the width, to 0.6.
 */
export const FIT_MIN_ZOOM = 0.8

/** The least zoom a fit goes to when the drawing fits across and only its height is short. */
export const TALL_FIT = 0.7

/**
 * How wide a graph may be drawn before its ranks are wrapped onto rows: about what a canvas shows
 * at `FIT_MIN_ZOOM` with the fit's padding around it.
 */
export const WRAP_WIDTH = 1120
