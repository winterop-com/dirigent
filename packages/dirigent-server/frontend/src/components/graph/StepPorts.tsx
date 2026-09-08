import { Handle, Position } from '@xyflow/react'

/**
 * Where an edge ends, and -- on a canvas that edits -- where one is drawn from.
 *
 * ONE COMPONENT, TWO MODES, because a port that differed between the two graphs would be a
 * second decision about the same dot. Left is what a step waits for and right is what waits for
 * it, which is the direction elk lays the pipeline out in.
 *
 * A VIEW OFFERS NO PORT. React Flow routes an edge to a handle and draws no edge at all without
 * one, so a run's graph keeps the two anchors and neither of them is visible, connectable or
 * under the pointer: `.dg-port` is the dot index.css paints, and only the editable mode wears it.
 */
export function StepPorts({ editable }: { editable: boolean }) {
    return (
        <>
            <Handle
                type="target"
                position={Position.Left}
                isConnectable={editable}
                className={editable ? 'dg-port' : undefined}
            />
            <Handle
                type="source"
                position={Position.Right}
                isConnectable={editable}
                className={editable ? 'dg-port' : undefined}
            />
        </>
    )
}
