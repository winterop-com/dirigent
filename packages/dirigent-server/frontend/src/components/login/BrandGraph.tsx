import { useLayoutEffect, useRef, useState } from 'react'

import {
    ACCENT_DOTS,
    BAR_H,
    BAR_INSET,
    BAR_RADIUS,
    BAR_W,
    DOT_INSET,
    DOT_R,
    FAILED,
    HEAD,
    LINKS,
    NODES,
    NODE_H,
    NODE_RADIUS,
    NODE_W,
    arcsFor,
    edgePath,
    isLit,
    layout,
    linkKey,
    placedOf,
} from '@/components/login/graph'

const GLOW = 'login-graph-glow'
const HALO = 'login-graph-halo'

type Box = { width: number; height: number }

/**
 * The run behind the login lockup: the app's one decorative element.
 *
 * IT SAYS WHAT THE PRODUCT IS, WHICH IS THE ONE THING A DOOR MAY DECORATE WITH. A graph of
 * steps with one run lit through it is the shape every screen behind this one draws, and it
 * sits a rung or two above the pane's ground so it stays under the lockup rather than beside
 * it.
 *
 * THE AMBER IS THE PATH THE RUN TOOK, and the head of it is the only solid node. One step is
 * drawn in the failed hue, because a graph where nothing ever goes wrong is not this graph.
 *
 * IT IS FITTED TO THE BOX AND CENTRED IN IT. The box the pane gives it is measured, the viewBox
 * is that many pixels, and `layout` fits the drawing at its own shape inside them -- bounded
 * above so a wide pane does not magnify it, with the rows taking a little of a tall pane's
 * spare height and the rest left as ground either side of it.
 */
export function BrandGraph() {
    const box = useRef<HTMLDivElement>(null)
    const [size, setSize] = useState<Box | null>(null)

    useLayoutEffect(() => {
        const element = box.current
        if (element === null) return
        const observer = new ResizeObserver((entries) => {
            const measured = entries[0].contentRect
            setSize({ width: measured.width, height: measured.height })
        })
        observer.observe(element)
        return () => {
            observer.disconnect()
        }
    }, [])

    return (
        <div ref={box} className="pointer-events-none size-full">
            {size !== null && size.width > 0 && size.height > 0 && (
                <Drawing width={size.width} height={size.height} />
            )}
        </div>
    )
}

function Drawing({ width, height }: Box) {
    const drawn = layout(NODES, width, height)
    const arcs = arcsFor(width, height)
    const at = (id: string) => placedOf(drawn.nodes, id)
    const head = at(HEAD)

    return (
        <svg viewBox={`0 0 ${width} ${height}`} className="size-full" fill="none" aria-hidden>
            <defs>
                {/* Both filter regions are stated rather than left at the default -10%/120%,
                    because a blur that wide off a thin path is clipped by it. */}
                <filter id={GLOW} x="-25%" y="-25%" width="150%" height="150%">
                    <feGaussianBlur stdDeviation="6" result="blurred" />
                    <feMerge>
                        <feMergeNode in="blurred" />
                        <feMergeNode in="SourceGraphic" />
                    </feMerge>
                </filter>
                <filter id={HALO} x="-100%" y="-100%" width="300%" height="300%">
                    <feGaussianBlur stdDeviation="14" />
                </filter>
            </defs>

            {/* The arcs are the box's own and stand outside the transform: they are ground
                rather than part of the run, and a ground that grew with the drawing would
                read as a second graph. */}
            <g className="stroke-terminal-graph-faint" strokeWidth={1}>
                {arcs.radii.map((r) => (
                    <circle key={r} cx={arcs.cx} cy={arcs.cy} r={r} />
                ))}
            </g>

            <g transform={`translate(${drawn.offsetX} ${drawn.offsetY}) scale(${drawn.scale})`}>
                <g className="stroke-terminal-graph-edge" strokeWidth={1.5}>
                    {LINKS.filter((link) => !isLit(link)).map((link) => (
                        <path key={linkKey(link)} d={edgePath(at(link[0]), at(link[1]))} />
                    ))}
                </g>

                <g className="stroke-terminal-accent" strokeWidth={4} opacity={0.28} filter={`url(#${GLOW})`}>
                    {LINKS.filter(isLit).map((link) => (
                        <path key={linkKey(link)} d={edgePath(at(link[0]), at(link[1]))} />
                    ))}
                </g>
                <g className="stroke-terminal-accent" strokeWidth={1.5}>
                    {LINKS.filter(isLit).map((link) => (
                        <path key={linkKey(link)} d={edgePath(at(link[0]), at(link[1]))} />
                    ))}
                </g>

                <circle
                    cx={head.x}
                    cy={head.y}
                    r={40}
                    className="fill-status-completed-with-errors"
                    opacity={0.35}
                    filter={`url(#${HALO})`}
                />

                {drawn.nodes.map((node) => {
                    const isHead = node.id === HEAD
                    const failed = node.id === FAILED
                    const x = node.x - NODE_W / 2
                    const y = node.y - NODE_H / 2
                    return (
                        <g key={node.id} filter={isHead ? `url(#${GLOW})` : undefined}>
                            <rect
                                x={x}
                                y={y}
                                width={NODE_W}
                                height={NODE_H}
                                rx={NODE_RADIUS}
                                strokeWidth={1}
                                className={
                                    isHead
                                        ? 'fill-status-completed-with-errors stroke-status-completed-with-errors'
                                        : failed
                                          ? 'fill-terminal-node stroke-status-failed'
                                          : 'fill-terminal-node stroke-terminal-node-edge'
                                }
                            />
                            <circle
                                cx={x + DOT_INSET}
                                cy={node.y}
                                r={DOT_R}
                                className={
                                    isHead
                                        ? 'fill-terminal'
                                        : failed
                                          ? 'fill-status-failed'
                                          : ACCENT_DOTS.has(node.id)
                                            ? 'fill-terminal-accent'
                                            : 'fill-terminal-muted'
                                }
                            />
                            <rect
                                x={x + BAR_INSET}
                                y={node.y - BAR_H / 2}
                                width={BAR_W}
                                height={BAR_H}
                                rx={BAR_RADIUS}
                                className={isHead ? 'fill-terminal' : 'fill-terminal-graph-edge'}
                            />
                        </g>
                    )
                })}
            </g>
        </svg>
    )
}
