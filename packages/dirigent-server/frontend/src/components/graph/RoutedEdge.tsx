import { BaseEdge, getSmoothStepPath, type Edge, type EdgeProps } from '@xyflow/react'
import { createContext, useContext } from 'react'

import { routedPath, type GraphPoint, type LayoutDirection } from '@/lib/dag-layout'

/** What a routed edge carries: elk's route for it, and whether that route is a curve. */
export interface RoutedEdgeData extends Record<string, unknown> {
    points?: GraphPoint[]
    curved: boolean
}

/** The edge kind a view draws once a reader asks for elk's routes. */
export type RoutedEdgeKind = Edge<RoutedEdgeData, 'routed'>

/**
 * One edge, drawn along the route elk decided rather than the one the canvas would.
 *
 * Until elk has answered there is no route, and the edge is the stepped line the canvas draws.
 */
export function RoutedEdge({
    id,
    data,
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    style,
    markerEnd,
    interactionWidth,
}: EdgeProps<RoutedEdgeKind>) {
    const points = data?.points
    const path =
        points !== undefined && points.length >= 2
            ? routedPath(points, data?.curved === true)
            : getSmoothStepPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })[0]
    return (
        <BaseEdge
            id={id}
            path={path}
            style={style}
            markerEnd={markerEnd}
            interactionWidth={interactionWidth}
        />
    )
}

/** Which way a view's ranks run, which is the side of a box an edge leaves and arrives on. */
export const DirectionContext = createContext<LayoutDirection>('right')

/** The direction the canvas a box stands on is laid out in. */
export function useLayoutDirection(): LayoutDirection {
    return useContext(DirectionContext)
}
