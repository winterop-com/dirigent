import { ReactFlowProvider, useReactFlow } from '@xyflow/react'
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from 'react'

import { BlockPicker } from '@winterop-com/sokkel-ui-graph/BlockPicker'
import type { GraphControls, GraphEditing } from '@winterop-com/sokkel-ui-graph/GraphCanvas'
import { GraphOverlay, type GraphAnchor } from '@winterop-com/sokkel-ui-graph/GraphOverlay'
import { GraphToolbarButton } from '@winterop-com/sokkel-ui-graph/GraphToolbar'
import { PipelineGraph as StepCanvas, type PipelineStep } from '@winterop-com/sokkel-ui-graph/PipelineGraph'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@winterop-com/sokkel-ui/primitives/dropdown-menu'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@/hooks/use-store'
import type { JsonMap } from '@/lib/api'
import { pickerBlocks, pickerGroups } from '@/lib/add-step'
import { catalogUnread, type BlockEntry } from '@/lib/blocks'
import { addStepAsked, relayoutAsked } from '@/lib/canvas-actions'
import { forgetPlacements, heldLayout, loadPlacements, placeStep, type Placement } from '@/lib/canvas-layout'
import { FIT_MIN_ZOOM, RANK_SPACING, WRAP_WIDTH } from '@/lib/dag-layout'
import { BLOCK_PICKER_WORDS, EDITOR_GRAPH_WORDS } from '@/lib/design-system'
import { cycleRefusal, cycleThrough } from '@/lib/graph-edits'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import {
    edgesIn,
    fanOutOf,
    sourceKindOf,
    stepEdited,
    stepHeading,
    stepNames,
    stepRuns,
    type DocumentEdits,
} from '@/lib/pipeline-document'
import { stepMissing, type Unmet } from '@/lib/requirements'
import { listeningLine, readPipelineSources, type SourceOut } from '@/lib/sources'

/**
 * The document's graph: the steps it declares and the edges its `depends_on` draws, drawn by
 * sokkel-ui-graph's `PipelineGraph` from one `PipelineStep` per step.
 *
 * Each box is titled by the step's name or key, its second line the key under a name and the
 * block it runs, or what a source listens to on a dashed box. A fan-out's count stands at the end
 * of the title line. A step whose block this instance does not publish wears `not installed` and
 * the issue saying so; one that differs from the version the instance holds wears `edited`. Every
 * box keeps room for either badge and for the issue mark, so an edit or the catalog landing
 * moves nothing.
 *
 * Given `editing`, the canvas reports every gesture and the document changes only through the
 * callbacks: an edge drawn or deleted is a `depends_on` entry, a box deleted is a step, a box let
 * go is a placement kept in `lib/canvas-layout`, and an edge that would close a loop is refused
 * while it is drawn. A connection let go over empty ground, a right-click on the ground, the
 * button beside the zoom, the empty canvas's button and the palette all open one block picker,
 * at the place they were asked from; a right-click on a box opens that box's own menu.
 *
 * This module is loaded lazily: React Flow is a large part of what this screen costs, and elk is a
 * chunk of its own fetched when the canvas asks for geometry.
 */

/** What a document with no read of its sources has: nothing, and the same nothing each time. */
const NO_SOURCES: readonly SourceOut[] = []

/** What another pipeline's arrangement amounts to here: nothing, and the same nothing each time. */
const NO_PLACEMENTS: Readonly<Record<string, Placement>> = {}

/** Every badge a box may come to wear, which each box keeps room for. */
const BADGES: readonly string[] = [LABELS.editor.canvas.edited, LABELS.editor.canvas.not_installed]

export interface PipelineGraphProps {
    /** The pipeline being edited, which is what an arrangement is kept under. */
    pipeline: string
    document: JsonMap
    /** The catalog this instance answered with, which is what the block picker offers. */
    blocks: BlockEntry[]
    edits: DocumentEdits
    /** What this instance has not got of what the document names. */
    unmet: Unmet
    selected: string | null
    onSelect: (step: string | null) => void
    /** A block was chosen: a step runs it, waits for `after` when given, and stands at `at` when given. */
    onAddStep: (block: string, after: string | null, at: Placement | null) => void
    /** An edge was drawn: `to` is to wait for `from`. */
    onConnect: (from: string, to: string) => void
    /** An edge was deleted: `to` is to stop waiting for `from`. */
    onDisconnect: (from: string, to: string) => void
    /** A step was deleted: it goes, and so does every reference to it. */
    onRemoveStep: (step: string) => void
    /** An edge was refused, for this reason. */
    onRefuse: (reason: string) => void
    /** What the empty canvas offers besides adding a step. */
    emptyAction?: ReactNode
    /** Draws the document and edits nothing: no ports, no menus, no add button. */
    readOnly?: boolean
}

/** Where the block picker stands, the step it adds after, and where that step is placed. */
interface Picking {
    at: GraphAnchor
    after: string | null
    place: Placement | null
}

/** The provider is this component's own, so it can turn a point on the screen into one on the graph. */
export function PipelineGraph(props: PipelineGraphProps) {
    return (
        <ReactFlowProvider>
            <EditorGraph {...props} />
        </ReactFlowProvider>
    )
}

function EditorGraph({
    pipeline,
    document,
    blocks,
    edits,
    unmet,
    selected,
    onSelect,
    onAddStep,
    onConnect,
    onDisconnect,
    onRemoveStep,
    onRefuse,
    emptyAction,
    readOnly = false,
}: PipelineGraphProps) {
    const flow = useReactFlow()
    const host = useRef<HTMLDivElement | null>(null)
    const layout = useStore(heldLayout)
    const controls = useRef<GraphControls | null>(null)
    const [picking, setPicking] = useState<Picking | null>(null)
    const [onNode, setOnNode] = useState<{ step: string; over: { x: number; y: number } } | null>(null)

    useEffect(() => {
        loadPlacements(pipeline)
    }, [pipeline])

    // The palette's ask opens the picker over the canvas's middle, since a keyboard gesture has no place on the screen.
    const asked = useStore(addStepAsked)
    useEffect(() => {
        if (asked === 0 || readOnly || host.current === null) return
        const box = host.current.getBoundingClientRect()
        const at = flow.screenToFlowPosition({ x: box.x + box.width / 2, y: box.y + box.height / 3 })
        // The palette's ask is the external event this synchronizes with; the picker opens once per bump.
        // oxlint-disable-next-line react/set-state-in-effect
        setPicking({ at, after: null, place: null })
    }, [asked, flow, readOnly])
    const tidy = useStore(relayoutAsked)
    useEffect(() => {
        if (tidy === 0) return
        forgetPlacements()
        controls.current?.fit()
    }, [tidy])

    // What this instance says each source listens to, asked only of a document with one. A
    // pipeline nothing has applied answers 404, and its boxes say their kind.
    const hasSource = stepNames(document).some((name) => sourceKindOf(document, name) !== null)
    const held = useRead(
        useCallback(
            () => (hasSource ? readPipelineSources(pipeline) : Promise.resolve(null)),
            [hasSource, pipeline],
        ),
    )
    const sources = held.value?.items ?? NO_SOURCES

    const steps = useMemo<PipelineStep[]>(() => {
        const needs = new Map<string, string[]>()
        for (const [from, to] of edgesIn(document)) needs.set(to, [...(needs.get(to) ?? []), from])
        return stepNames(document).map((name) => {
            const heading = stepHeading(document, name)
            const kind = sourceKindOf(document, name)
            const block = stepRuns(document, name)
            const said = kind === null ? block : listeningLine(sources, name, kind)
            const line = heading.code === null ? said : `${heading.code} · ${said}`
            const fan = fanOutOf(document, name)
            const missing = stepMissing(unmet, name)
            const notInstalled = LABELS.editor.canvas.not_installed_title(block)
            return {
                code: name,
                name: heading.named ? heading.title : undefined,
                kind: said,
                needs: needs.get(name) ?? [],
                icon: kind === null ? undefined : ICONS.source,
                source: kind !== null,
                lineHint: kind === null ? undefined : LABELS.editor.canvas.listens_to(line),
                count: !fan.fanOut
                    ? undefined
                    : fan.items === null
                      ? LABELS.editor.canvas.fan_out_each
                      : LABELS.editor.canvas.fan_out_count(String(fan.items)),
                hint: !fan.fanOut
                    ? undefined
                    : fan.items === null
                      ? LABELS.editor.canvas.fan_out_each_title
                      : LABELS.editor.canvas.fan_out_count_title(String(fan.items)),
                badge: missing
                    ? { label: LABELS.editor.canvas.not_installed, tone: 'critical', title: notInstalled }
                    : stepEdited(edits, name)
                      ? { label: LABELS.editor.canvas.edited }
                      : undefined,
                reserveBadges: BADGES,
                reserveIssue: true,
                issues: missing ? [{ tone: 'critical', text: notInstalled }] : undefined,
            }
        })
    }, [document, edits, sources, unmet])

    const groups = useMemo(() => pickerGroups(blocks), [blocks])
    const offered = useMemo(() => pickerBlocks(blocks), [blocks])

    // An arrangement is one pipeline's, so another pipeline's is nothing until its own is read.
    const positions = layout.pipeline === pipeline ? layout.placements : NO_PLACEMENTS

    const editing = useMemo<GraphEditing>(
        () => ({
            onConnect,
            onDisconnect: (_edge, from, to) => {
                onDisconnect(from, to)
            },
            onRemove: onRemoveStep,
            onMove: placeStep,
            onNodeMenu: (step, at) => {
                setPicking(null)
                setOnNode({ step, over: { x: at.clientX, y: at.clientY } })
            },
            onPaneMenu: (at) => {
                setOnNode(null)
                setPicking({ at: { x: at.x, y: at.y }, after: null, place: null })
            },
            onDrop: (from, at) => {
                setOnNode(null)
                setPicking({ at: { x: at.x, y: at.y }, after: from, place: { x: at.x, y: at.y } })
            },
            canConnect: (from, to) => {
                const cycle = cycleThrough(document, from, to)
                return cycle === null ? null : cycleRefusal(from, to, cycle)
            },
            onRefuse: (_from, _to, reason) => {
                onRefuse(reason)
            },
        }),
        [document, onConnect, onDisconnect, onRefuse, onRemoveStep],
    )

    // The picker opens beside the button it was asked from.
    const pickFrom = (event: MouseEvent<HTMLButtonElement>) => {
        const box = event.currentTarget.getBoundingClientRect()
        setOnNode(null)
        setPicking({
            at: flow.screenToFlowPosition({ x: box.left, y: box.bottom }),
            after: null,
            place: null,
        })
    }

    const close = () => {
        setPicking(null)
    }

    return (
        <div ref={host} className="absolute inset-0">
            <StepCanvas
                steps={steps}
                selected={selected}
                onSelect={onSelect}
                direction="right"
                routing="orthogonal"
                fitMinZoom={FIT_MIN_ZOOM}
                narrowFit={false}
                wrapWidth={WRAP_WIDTH}
                positions={positions}
                editing={readOnly ? undefined : editing}
                onControls={(handed) => {
                    controls.current = handed
                }}
                extraControls={
                    readOnly ? undefined : (
                        <GraphToolbarButton
                            label={LABELS.editor.canvas.add_step}
                            className="rounded-none"
                            onClick={pickFrom}
                        >
                            <ICONS.create aria-hidden />
                        </GraphToolbarButton>
                    )
                }
                emptyAction={
                    readOnly && emptyAction === undefined ? undefined : (
                        <div className="flex items-center gap-2">
                            {!readOnly && (
                                <Button variant="outline" size="sm" onClick={pickFrom}>
                                    <ICONS.create aria-hidden />
                                    {LABELS.editor.canvas.add_step}
                                </Button>
                            )}
                            {emptyAction}
                        </div>
                    )
                }
                words={EDITOR_GRAPH_WORDS}
            >
                {picking !== null && !readOnly && (
                    <GraphOverlay at={picking.at} link={picking.after ?? undefined} onClose={close}>
                        <BlockPicker
                            blocks={offered}
                            groups={groups}
                            loading={catalogUnread(blocks)}
                            showDescription
                            title={
                                picking.after === null
                                    ? LABELS.editor.canvas.add_step
                                    : LABELS.editor.canvas.add_step_after(picking.after)
                            }
                            onPick={(block) => {
                                close()
                                onAddStep(block.kind, picking.after, picking.place)
                            }}
                            onClose={close}
                            words={BLOCK_PICKER_WORDS}
                        />
                    </GraphOverlay>
                )}
            </StepCanvas>

            {onNode !== null && (
                <StepMenuAt
                    step={onNode.step}
                    at={onNode.over}
                    onAddAfter={() => {
                        const box = flow.getNode(onNode.step)
                        setOnNode(null)
                        if (box === undefined) return
                        const place = {
                            x: box.position.x + (box.width ?? 0) + RANK_SPACING,
                            y: box.position.y,
                        }
                        setPicking({ at: place, after: onNode.step, place })
                    }}
                    onRemove={() => {
                        setOnNode(null)
                        onRemoveStep(onNode.step)
                    }}
                    onClose={() => {
                        setOnNode(null)
                    }}
                />
            )}
        </div>
    )
}

/**
 * A box's own menu: one more step after this one, and this one taken out. Its anchor is an
 * element of no size at the pointer, so the popup stays inside the viewport.
 */
function StepMenuAt({
    step,
    at,
    onAddAfter,
    onRemove,
    onClose,
}: {
    step: string
    at: { x: number; y: number }
    onAddAfter: () => void
    onRemove: () => void
    onClose: () => void
}) {
    return (
        <DropdownMenu
            open
            onOpenChange={(next) => {
                if (!next) onClose()
            }}
        >
            <DropdownMenuTrigger
                aria-label={step}
                tabIndex={-1}
                data-menu-anchor
                className="pointer-events-none fixed size-0"
                style={{ left: at.x, top: at.y }}
            />
            <DropdownMenuContent align="start" className="w-56">
                <p className="truncate px-2 py-1.5 font-mono text-xs text-faint">{step}</p>
                <DropdownMenuItem onClick={onAddAfter}>{LABELS.editor.canvas.add_after}</DropdownMenuItem>
                <DropdownMenuItem className="destructive-action" onClick={onRemove}>
                    {LABELS.editor.canvas.delete_step}
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
