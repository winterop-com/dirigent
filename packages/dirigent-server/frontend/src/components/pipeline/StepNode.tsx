import { type Node, type NodeProps } from '@xyflow/react'
import { Layers2 } from 'lucide-react'
import type { CSSProperties } from 'react'

import { StepPorts } from '@/components/graph/StepPorts'
import { statusTokens } from '@/lib/status'
import { cn } from '@/lib/utils'

/** What one node of the document's graph carries. */
export interface DocumentNodeData extends Record<string, unknown> {
    /** What the step is titled: its own name when it has one, else its key. */
    title: string
    /** Whether the title is a name, which decides whether the title wears the mono face. */
    named: boolean
    /** The step's key in the document, drawn under a title that is not already it. */
    code: string | null
    /** The block it runs. */
    block: string
    /** Whether this step differs from the version the instance holds. */
    edited: boolean
    /** Whether the block it names is one this instance does not publish. */
    missing: boolean
    /** Whether the step runs once per item, and over how many where the list is written out. */
    fanOut: boolean
    fanOutItems: number | null
    /** Whether this canvas is the editor's, which is what puts ports on the box. */
    editable: boolean
}

/** The node kind this graph draws, which is the only one it has. */
export type DocumentNode = Node<DocumentNodeData, 'step'>

/**
 * One step of the stored document, as a box on the graph.
 *
 * IT DRAWS THE DOCUMENT, NOT A RUN. There is no status here because nothing is running: what a
 * step wears instead is whether it differs from the version the instance holds -- a document
 * nothing has applied differs from nothing, so none of its boxes is marked -- and, louder,
 * because it is the one that will stop the run, whether the block it names is installed here.
 * A missing block takes the corner from an edit, because an edit that cannot run is not the
 * news.
 *
 * TWO LINES, AND THE CONFIG IS NOT ONE OF THEM. What a step is called and what it runs are what
 * a reader is scanning the canvas for; its config is a map of any size, and one truncated line
 * of it crowds the box without answering anything. The step's own pane holds the whole of it.
 * A step that carries a name is titled with it and its key goes on the mono line beneath, ahead
 * of the block -- the key is what `depends_on` and every log line reference, so it is never off
 * the box. The box is the same one
 * the run graph draws -- `.step-node` in index.css -- so a pipeline reads the same in both
 * places, and the left edge takes the neutral hue rather than a state's. It is marked
 * `data-document` so that the foot of it can hug the second line: what a run's box keeps that
 * room for -- a state, a duration, a strip of elements -- a document has none of.
 *
 * THE CHOSEN BOX SAYS SO TWICE, IN NEUTRAL. The halo is the ring around it and the title goes to
 * full weight on the foreground ink -- a selection is a reading position rather than an action,
 * so it takes none of the identity colour, which on this canvas means an unapplied edit.
 *
 * A FAN-OUT SAYS SO ON THE MONO LINE, in the neutral ink the rest of that line is in: what a
 * step is drawn in is a status and nothing else, so `for_each` is a glyph and a count rather
 * than a second colour. The count is there where the document writes the list out and is the
 * word "each" where it writes an expression a run resolves. The marker keeps its width and the
 * line beside it truncates, so it is on the box at every zoom the box is read at.
 *
 * ITS PORTS ARE WHERE AN EDGE IS DRAWN FROM. On this canvas a step's prerequisites are edited by
 * dragging between the dots as well as by the chips in its own pane, so the dots are visible and
 * connectable here and on no other graph.
 */
export function StepNode({ data, selected }: NodeProps<DocumentNode>) {
    const tokens = statusTokens('pending') as CSSProperties

    return (
        <div
            className="step-node"
            style={tokens}
            data-document="true"
            data-selected={selected === true}
            data-editable={data.editable}
        >
            <StepPorts editable={data.editable} />
            <div className="flex items-center gap-2">
                <span
                    data-testid="step-title"
                    className={cn(
                        'truncate text-sm',
                        !data.named && 'font-mono',
                        selected === true ? 'text-foreground font-bold' : 'font-semibold',
                    )}
                >
                    {data.title}
                </span>
                {data.missing && (
                    <span
                        className="border-critical text-critical ml-auto shrink-0 rounded-sm border px-1 text-xs"
                        title={`${data.block} is not installed on this instance, so this step will fail`}
                    >
                        not installed
                    </span>
                )}
                {data.edited && !data.missing && (
                    <span className="border-primary text-primary ml-auto shrink-0 rounded-sm border px-1 text-xs">
                        edited
                    </span>
                )}
            </div>
            <span className="flex items-center gap-2">
                <span data-testid="step-line" className="text-muted-foreground truncate font-mono text-xs">
                    {data.code === null ? data.block : `${data.code} · ${data.block}`}
                </span>
                {data.fanOut && (
                    <span
                        data-testid="step-fan-out"
                        className="text-faint ml-auto flex shrink-0 items-center gap-1 font-mono text-xs"
                        title={
                            data.fanOutItems === null
                                ? 'for_each: runs once per item of the list it is given'
                                : `for_each: runs once per item, ${String(data.fanOutItems)} of them`
                        }
                    >
                        <Layers2 className="size-3" aria-hidden />
                        {data.fanOutItems === null ? 'each' : `×${String(data.fanOutItems)}`}
                    </span>
                )}
            </span>
        </div>
    )
}
