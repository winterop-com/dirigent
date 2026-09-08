import { type Node, type NodeProps } from '@xyflow/react'
import type { CSSProperties } from 'react'

import { StepPorts } from '@/components/graph/StepPorts'
import { StatusDot } from '@/components/run/StatusChip'
import { formatDuration } from '@/lib/format'
import { headingOf } from '@/lib/identity'
import { nodeTone, type StepView } from '@/lib/run-detail'
import { statusTokens } from '@/lib/status'
import { cn } from '@/lib/utils'

/** What one node of the run graph carries. */
export interface StepNodeData extends Record<string, unknown> {
    view: StepView
}

/** The node kind this graph draws, which is the only one it has. */
export type StepNode = Node<StepNodeData, 'step'>

/**
 * One step, as a box on the graph.
 *
 * IT IS HEADED THE WAY THE EDITOR HEADS THE SAME STEP: the title is the name the document gave
 * the step and its key otherwise, and where the title is a name the key goes on the mono line
 * beneath, ahead of the block. A run of a document that named its steps reads as that document.
 *
 * A FAN-OUT STEP IS THIS ONE BOX. Its elements are a strip inside it -- named while there are
 * few enough to name, counted once there are not -- because sixty items are sixty attempts of
 * one step and not sixty places in the pipeline. The strip is decided in `lib/run-detail`; this
 * only draws what it decided.
 *
 * THE COUNT ON THE HEADER IS ITEMS, NOT TRIES. A fan-out step's attempts are its elements, and
 * how wide the step is is what somebody reads off the graph; how many times one element was
 * retried is a fact about that element and is on its chip in the strip.
 *
 * IT SAYS HOW LONG THE STEP TOOK, on the right of its last line, in the same reading the
 * panel's `took` fact is drawn from -- `lib/run-detail` measures it once so the two cannot
 * disagree. A step that has not started says nothing there.
 *
 * WHAT IT IS DRAWN IN IS `nodeTone`, NOT THE FOLDED OUTCOME. A fan-out whose failures the run
 * tolerated is amber rather than red, because that is what the run's own chip says about it.
 *
 * THIS GRAPH OFFERS NO PORTS. It is a view: nothing is connected, disconnected or dragged here,
 * so `StepPorts` is drawn in its view mode -- the anchors an edge has to end at, and nothing
 * visible or connectable. A pipeline is edited on its own screen.
 */
export function StepNode({ data, selected }: NodeProps<StepNode>) {
    const { view } = data
    const tone = nodeTone(view)
    const tokens = statusTokens(tone) as CSSProperties
    const heading = headingOf(view.node)

    return (
        <div className="step-node" style={tokens} data-selected={selected === true} data-outcome={tone}>
            <StepPorts editable={false} />
            <div className="flex items-center gap-2">
                <StatusDot status={tone} />
                <span
                    data-testid="step-title"
                    className={cn('truncate text-sm font-semibold', !heading.named && 'font-mono')}
                >
                    {heading.title}
                </span>
                {view.node.fan_out && view.node.items_total > 0 && (
                    <span className="text-faint ml-auto shrink-0 font-mono text-xs">
                        {view.node.items_total} items
                    </span>
                )}
            </div>
            <span data-testid="step-line" className="text-muted-foreground truncate font-mono text-xs">
                {heading.code === null ? view.node.block : `${heading.code} · ${view.node.block}`}
            </span>
            <div className="flex items-baseline gap-2">
                <span className="text-faint min-w-0 truncate text-xs" title={view.detail ?? undefined}>
                    {view.detail ?? ' '}
                </span>
                {view.duration_ms !== null && (
                    <span className="text-faint ml-auto shrink-0 font-mono text-xs">
                        {formatDuration(view.duration_ms)}
                    </span>
                )}
            </div>
            {view.node.fan_out && <ItemStrip view={view} />}
        </div>
    )
}

/** The elements of a fan-out step: named while they fit, counted once they do not. */
function ItemStrip({ view }: { view: StepView }) {
    if (view.strip.kind === 'empty') {
        return <span className="text-faint truncate text-xs">fans out</span>
    }
    if (view.strip.kind === 'counts') {
        return (
            <span className="text-muted-foreground truncate text-xs">
                {view.strip.counts.map((count) => `${String(count.count)} ${count.status}`).join(' · ')}
            </span>
        )
    }
    return (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 overflow-hidden">
            {view.strip.items.map((item) => (
                <span key={item.id} className="text-muted-foreground flex items-center gap-1 text-xs">
                    <StatusDot status={item.status} />
                    <span className="max-w-20 truncate font-mono">{item.key}</span>
                    {item.retry !== null && <span className="text-faint">{item.retry}</span>}
                </span>
            ))}
        </div>
    )
}
