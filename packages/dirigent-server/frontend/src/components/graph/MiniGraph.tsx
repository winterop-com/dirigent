import { useMemo } from 'react'

import { MINI_BOX_HEIGHT, MINI_BOX_WIDTH, miniLayout, miniScale, type MiniStep } from '@/lib/mini-graph'

/**
 * A pipeline's shape at the scale of a row.
 *
 * Every miniature is drawn at the same pitch, so a longer strip is a longer pipeline, until the
 * room it is given runs out; a deeper one is drawn smaller rather than cut. The failed step is
 * the only box with a colour.
 */
export function MiniGraph({
    steps,
    failed = null,
    width,
    height,
}: {
    steps: readonly MiniStep[]
    failed?: string | null
    /** The most room the strip may take. */
    width: number
    height: number
}) {
    const layout = useMemo(() => miniLayout(steps, failed), [steps, failed])
    if (layout.boxes.length === 0) return null
    const scale = miniScale(layout, { width, height })
    return (
        <svg
            className="mini-graph shrink-0"
            width={Math.ceil(layout.width * scale) + 2}
            height={Math.ceil(layout.height * scale) + 2}
            viewBox={`-1 -1 ${String(layout.width + 2)} ${String(layout.height + 2)}`}
            aria-hidden
        >
            {layout.edges.map((edge) => (
                <path key={edge.id} className="mini-edge" d={edge.d} />
            ))}
            {layout.boxes.map((box) => (
                <g key={box.code}>
                    <title>{box.label}</title>
                    {box.fanOut && (
                        <rect
                            className="mini-box"
                            data-behind
                            x={box.x + 2}
                            y={box.y + 2}
                            width={MINI_BOX_WIDTH}
                            height={MINI_BOX_HEIGHT}
                        />
                    )}
                    <rect
                        className="mini-box"
                        data-source={box.source || undefined}
                        data-failed={box.failed || undefined}
                        x={box.x + 0.5}
                        y={box.y + 0.5}
                        width={MINI_BOX_WIDTH - 1}
                        height={MINI_BOX_HEIGHT - 1}
                    />
                </g>
            ))}
        </svg>
    )
}
