import { Handle, Position } from '@xyflow/react'

import { useLayoutDirection } from '@/components/graph/RoutedEdge'

/**
 * Where an edge ends, and -- on a canvas that edits -- where one is drawn from.
 *
 * ONE COMPONENT, TWO MODES, because a port that differed between the two graphs would be a
 * second decision about the same dot. The side a step waits on is the side its prerequisites are
 * drawn on: left and right on a graph laid out left to right, top and bottom on one laid out down.
 *
 * A VIEW OFFERS NO PORT. React Flow routes an edge to a handle and draws no edge at all without
 * one, so a run's graph keeps the two anchors and neither of them is visible, connectable or
 * under the pointer: `.dg-port` is the dot index.css paints, and only the editable mode wears it.
 */
export function StepPorts({ editable }: { editable: boolean }) {
    const down = useLayoutDirection() === 'down'
    return (
        <>
            <Handle
                type="target"
                position={down ? Position.Top : Position.Left}
                isConnectable={editable}
                className={editable ? 'dg-port' : undefined}
            />
            <Handle
                type="source"
                position={down ? Position.Bottom : Position.Right}
                isConnectable={editable}
                className={editable ? 'dg-port' : undefined}
            />
        </>
    )
}
