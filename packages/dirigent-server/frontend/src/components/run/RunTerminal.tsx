import { ArrowDown, Copy, Download, PanelBottomClose, SquareTerminal } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useDragSize } from '@/hooks/use-drag-size'
import { useStore } from '@/hooks/use-store'
import { ApiError } from '@/lib/api'
import { formatClock } from '@/lib/format'
import { followTails } from '@/lib/preferences'
import { itemLabels, itemOfEntry, type RunDetailState } from '@/lib/run-detail'
import { readLogs, type LogEntryOut } from '@/lib/runs'
import {
    asNdjson,
    clampTerminalHeight,
    copyText,
    countLines,
    downloadName,
    emptyNote,
    endNote,
    EVERY_LINE,
    fieldsText,
    LEVEL_LABELS,
    LEVELS,
    lineCount,
    setTerminalHeight,
    stepChoices,
    stepOf,
    terminalHeight,
    TERMINAL_MAX_HEIGHT,
    TERMINAL_MIN_HEIGHT,
    toggleTerminal,
    visibleLines,
    type LineFilters,
} from '@/lib/terminal'
import { runSettled } from '@/lib/status'
import type { LogLevel } from '@/lib/status'
import { cn } from '@/lib/utils'

export const HIDE_TERMINAL_LABEL = 'Hide the terminal'
export const RESIZE_TERMINAL_LABEL = 'Resize the terminal'
export const COPY_LINES_LABEL = 'Copy the lines on screen'
export const DOWNLOAD_LOG_LABEL = 'Download every line as NDJSON'
export const LEVEL_LABEL = 'Least level shown'
export const STEP_LABEL = 'Filter by step'
export const MATCH_LABEL = 'Filter lines by text'
export const NEWEST_LABEL = 'Jump to newest'

/** How far one arrow press moves the top edge. A keyboard has to do what the pointer does. */
const KEYBOARD_STEP = 16

/** How far off the bottom counts as having scrolled away, in pixels of slack. */
const TAIL_SLACK = 24

/** What the step select's "no step at all" row is worth, which is every step. */
const EVERY_STEP = ''

/** How many pages of `$logs` a download walks before it stops asking. Fifty of them is 25,000 lines. */
const DOWNLOAD_PAGE_LIMIT = 50

/** How each level is inked on the terminal's own ground, which is dark in both palettes. */
const LEVEL_INK: Record<string, string> = {
    debug: 'text-terminal-faint',
    info: 'text-terminal-muted',
    warning: 'text-terminal-warning',
    error: 'text-terminal-critical',
}

/**
 * Everything one run said, as a console across the foot of the screen.
 *
 * THE LINES COME FROM THE RUN'S ONE STREAM. `runs/{id}/$events` already carries every line the
 * run wrote; the screen holds them in one reducer and this draws that list. There is no second
 * connection here and there must never be one -- the drawer, the step's log pane and the graph
 * are three readings of one state.
 *
 * EVERY STEP INTERLEAVED, IN ARRIVAL ORDER. What happened to a run is a sequence, and the order
 * lines arrived in is the answer. The step select is there for whoever is asking the other
 * question, and the step prefix on each line opens that step in the panel.
 *
 * DARK IN BOTH PALETTES, AND THAT IS DELIBERATE. A console is not a card: it is the one surface
 * in this app the light palette does not invert, the same way a code block on a light page is
 * not inverted. The header strip above it is ordinary app chrome and stays on the surface
 * ladder, so every control in it is a design-system control with nothing re-inked.
 *
 * IT FOLLOWS THE TAIL UNTIL SOMEBODY SCROLLS UP, which is `lib/preferences`' own setting and
 * the same rule the step's log pane is written to: a console that jumped to the bottom while
 * somebody was reading what failed would be unreadable during exactly the run that matters.
 */
export function RunTerminal({
    state,
    runId,
    onSelectStep,
}: {
    state: RunDetailState
    runId: string
    /** What a line's step prefix does: select that step and open it in the panel. */
    onSelectStep: (step: string) => void
}) {
    const height = useStore(terminalHeight)
    const wanted = useStore(followTails)
    const drawer = useRef<HTMLElement | null>(null)
    const lines = useRef<HTMLDivElement>(null)
    const { dragging, beginResize } = useDragSize('y', height, -1, setTerminalHeight, clampTerminalHeight, drawer)

    const [filters, setFilters] = useState<LineFilters>(EVERY_LINE)
    // What the reader did to this console, and what they set for every log pane: both follow.
    const [scrolledAway, setScrolledAway] = useState(false)
    const [saving, setSaving] = useState(false)
    const following = wanted && !scrolledAway

    // The lines carry the attempt that wrote them and no label; the attempts on the same stream
    // carry theirs, so which element a line belongs to is a join over what is already held. The
    // search reads it too, because it is drawn on the line.
    const labels = useMemo(() => itemLabels(state), [state])
    const shown = useMemo(() => visibleLines(state.logs, filters, labels), [state.logs, filters, labels])
    const drawn = useMemo(() => countLines(shown), [shown])
    const held = useMemo(() => countLines(state.logs), [state.logs])
    const counted = lineCount(drawn, held)
    const steps = stepChoices(state)

    const toBottom = useCallback(() => {
        const element = lines.current
        if (element === null) return
        element.scrollTop = element.scrollHeight
        setScrolledAway(false)
    }, [])

    useEffect(() => {
        const element = lines.current
        if (element === null || !following || shown.length === 0) return
        element.scrollTop = element.scrollHeight
    }, [shown.length, following])

    const copy = () => {
        void navigator.clipboard?.writeText(copyText(shown)).then(
            () => toast.success(drawn === 1 ? '1 line copied' : `${String(drawn)} lines copied`),
            () => toast.error('this browser would not give up its clipboard'),
        )
    }

    /**
     * Save the whole of the run's log, which is more than this screen holds.
     *
     * FETCHED AND BLOBBED RATHER THAN LINKED. `GET /runs/{id}/$logs` answers a page of JSON with
     * no content-disposition on it, so an anchor pointed at that path would navigate to a
     * listing rather than save a file -- and NDJSON is a rendering of those pages rather than
     * what the endpoint returns. So the pages are walked through `apiFetch` like every other
     * read and written out here, with no change asked of the server.
     */
    const download = () => {
        setSaving(true)
        void (async () => {
            const collected: LogEntryOut[] = []
            let after: string | null = null
            for (let page = 0; page < DOWNLOAD_PAGE_LIMIT; page += 1) {
                // A cursor walk is sequential by definition: the next page is named by this one.
                // oxlint-disable-next-line no-await-in-loop
                const answer = await readLogs(runId, after)
                collected.push(...answer.items)
                after = answer.next
                if (after === null) break
            }
            return collected
        })().then(
            (collected) => {
                setSaving(false)
                const url = URL.createObjectURL(new Blob([asNdjson(collected)], { type: 'application/x-ndjson' }))
                const anchor = document.createElement('a')
                anchor.href = url
                anchor.download = downloadName(runId)
                // In the document, because a click on an anchor no document holds does nothing.
                document.body.append(anchor)
                anchor.click()
                anchor.remove()
                URL.revokeObjectURL(url)
                toast.success(`${String(collected.length)} lines saved`)
            },
            (error: unknown) => {
                setSaving(false)
                toast.error(error instanceof ApiError ? error.problem.detail : 'the server did not answer')
            },
        )
    }

    return (
        <>
            <div
                role="separator"
                aria-orientation="horizontal"
                aria-label={RESIZE_TERMINAL_LABEL}
                aria-valuenow={height}
                aria-valuemin={TERMINAL_MIN_HEIGHT}
                aria-valuemax={TERMINAL_MAX_HEIGHT}
                tabIndex={0}
                data-dragging={dragging}
                onPointerDown={beginResize}
                onKeyDown={(event) => {
                    if (event.key === 'ArrowUp') setTerminalHeight(height + KEYBOARD_STEP)
                    else if (event.key === 'ArrowDown') setTerminalHeight(height - KEYBOARD_STEP)
                    else return
                    event.preventDefault()
                }}
                className="resize-handle h-1.5 shrink-0 cursor-row-resize touch-none"
            />
            <section
                ref={drawer}
                aria-label="Run terminal"
                data-run-terminal="true"
                className="border-border-strong flex shrink-0 flex-col overflow-hidden rounded-md border"
                style={{ height }}
            >
                <div className="bg-sidebar border-border flex flex-wrap items-center gap-2 border-b px-3 py-2">
                    <span className="text-faint flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase">
                        <SquareTerminal className="size-4" aria-hidden />
                        Terminal
                    </span>

                    <Select
                        value={filters.level}
                        onValueChange={(chosen) => {
                            setFilters((current) => ({ ...current, level: String(chosen) as LogLevel }))
                        }}
                    >
                        <SelectTrigger size="sm" className="w-40" aria-label={LEVEL_LABEL}>
                            <SelectValue>{(value) => LEVEL_LABELS[String(value) as LogLevel]}</SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {LEVELS.map((level) => (
                                <SelectItem key={level} value={level}>
                                    {LEVEL_LABELS[level]}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>

                    <Select
                        value={filters.step}
                        onValueChange={(chosen) => {
                            setFilters((current) => ({ ...current, step: String(chosen) }))
                        }}
                    >
                        <SelectTrigger size="sm" className="w-44" aria-label={STEP_LABEL}>
                            <SelectValue>{(value) => (value === EVERY_STEP ? 'Every step' : String(value))}</SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value={EVERY_STEP}>Every step</SelectItem>
                            {steps.map((step) => (
                                <SelectItem key={step} value={step}>
                                    {step}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>

                    <Input
                        className="h-7 w-48"
                        value={filters.match}
                        onChange={(event) => {
                            const match = event.target.value
                            setFilters((current) => ({ ...current, match }))
                        }}
                        placeholder="Search lines"
                        aria-label={MATCH_LABEL}
                    />

                    {counted !== null && <span className="text-muted-foreground text-xs">{counted}</span>}

                    <div className="flex-1" />

                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="ghost"
                                    size="icon-sm"
                                    aria-label={COPY_LINES_LABEL}
                                    disabled={shown.length === 0}
                                    onClick={copy}
                                >
                                    <Copy className="size-4" aria-hidden />
                                </Button>
                            }
                        />
                        <TooltipContent side="top">{COPY_LINES_LABEL}</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="ghost"
                                    size="icon-sm"
                                    aria-label={DOWNLOAD_LOG_LABEL}
                                    disabled={saving}
                                    onClick={download}
                                >
                                    <Download className="size-4" aria-hidden />
                                </Button>
                            }
                        />
                        <TooltipContent side="top">{DOWNLOAD_LOG_LABEL}</TooltipContent>
                    </Tooltip>
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="ghost"
                                    size="icon-sm"
                                    aria-label={HIDE_TERMINAL_LABEL}
                                    onClick={toggleTerminal}
                                >
                                    <PanelBottomClose className="size-4" aria-hidden />
                                </Button>
                            }
                        />
                        <TooltipContent side="top">{HIDE_TERMINAL_LABEL}</TooltipContent>
                    </Tooltip>
                </div>

                <div className="relative min-h-0 flex-1">
                    <div
                        ref={lines}
                        onScroll={(event) => {
                            const element = event.currentTarget
                            const room = element.scrollHeight - element.scrollTop - element.clientHeight
                            setScrolledAway(room > TAIL_SLACK)
                        }}
                        className="bg-terminal text-terminal-foreground h-full overflow-y-auto px-3 py-2 font-mono"
                    >
                        {shown.length === 0 ? (
                            <p className="text-terminal-muted text-xs">{emptyNote(filters, state.logs.length, runSettled(state.run?.status ?? null))}</p>
                        ) : (
                            shown.map((entry) => (
                                <Line
                                    key={entry.id}
                                    entry={entry}
                                    item={itemOfEntry(labels, entry.step_attempt_id)}
                                    onSelectStep={onSelectStep}
                                />
                            ))
                        )}
                        {/* The one place "is anything still coming" is answered: the status bar
                            says nothing once a run has settled, and the answer belongs where the
                            lines it is about are. */}
                        {state.stream === 'ended' && (
                            <p className="text-terminal-faint pt-2 text-xs">
                                {endNote(state.run?.status ?? null)}
                            </p>
                        )}
                    </div>
                    {!following && shown.length > 0 && (
                        <Button
                            variant="outline"
                            size="sm"
                            className="absolute inset-x-0 bottom-3 mx-auto w-fit shadow-md"
                            onClick={toBottom}
                        >
                            <ArrowDown aria-hidden />
                            {NEWEST_LABEL}
                        </Button>
                    )}
                </div>
            </section>
        </>
    )
}

/**
 * One line: when, how loud, which step, what it said, and whatever it said it with.
 *
 * THE STEP PREFIX IS A CONTROL WHERE THERE IS A STEP TO OPEN, and a label where there is not.
 * A run-level line -- the engine's own -- belongs to no step, and a prefix that lit under the
 * pointer and then did nothing would be a promise the line cannot keep.
 *
 * A FAN-OUT ELEMENT'S LABEL SITS BESIDE THE STEP, because five elements of one step write the
 * same sentence and the step alone does not say which of them wrote this one. It is not a
 * control: what opens is the step, and every element of it is on that one panel.
 */
function Line({
    entry,
    item,
    onSelectStep,
}: {
    entry: LogEntryOut
    /** The fan-out element this line was written for, or nothing where the step fans out to none. */
    item: string | null
    onSelectStep: (step: string) => void
}) {
    const step = stepOf(entry)
    const fields = fieldsText(entry.fields)
    return (
        <p className="text-xs break-words whitespace-pre-wrap" data-log-line={entry.level}>
            <span className="text-terminal-faint">{formatClock(entry.created_at)} </span>
            <span className={cn(LEVEL_INK[entry.level] ?? 'text-terminal-muted')}>{entry.level} </span>
            {step === null ? (
                <span className="text-terminal-faint">run</span>
            ) : (
                <button
                    type="button"
                    className="text-terminal-accent hover:underline focus-visible:underline focus-visible:outline-none"
                    onClick={() => {
                        onSelectStep(step)
                    }}
                >
                    {step}
                </button>
            )}
            {item !== null && <span className="text-terminal-faint"> [{item}]</span>}
            <span> {entry.message}</span>
            {fields !== null && <span className="text-terminal-muted"> {fields}</span>}
        </p>
    )
}
