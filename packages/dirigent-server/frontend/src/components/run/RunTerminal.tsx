import { useEffect, useMemo, useState } from 'react'
import { toast } from 'sonner'

import { Dock } from '@winterop-com/sokkel-ui/Dock'
import { IconButton } from '@winterop-com/sokkel-ui/IconButton'
import { LogView, type LogLevel as LineLevel, type LogLine } from '@winterop-com/sokkel-ui/LogView'
import { FilterChip } from '@winterop-com/sokkel-ui/FilterChip'
import { SearchField } from '@winterop-com/sokkel-ui/SearchField'
import { useStore } from '@winterop-com/sokkel-ui/hooks/use-store'
import { ApiError } from '@/lib/api'
import { filterWords, oneChosen, SEARCH_WORDS } from '@/lib/library-words'
import { formatClock } from '@/lib/format'
import { ICONS } from '@/lib/icons'
import { counted, LABELS } from '@/lib/labels'
import { followTails } from '@/lib/preferences'
import { itemLabels, itemOfEntry, type RunDetailState } from '@/lib/run-detail'
import { readLogs, type LogEntryOut } from '@/lib/runs'
import {
    asNdjson,
    copyText,
    countLines,
    downloadName,
    emptyNote,
    endNote,
    EVERY_LINE,
    fieldsText,
    LEVELS,
    lineCount,
    setTerminalHeight,
    stepChoices,
    stepOf,
    terminalHeight,
    TERMINAL_DEFAULT_HEIGHT,
    TERMINAL_MAX_HEIGHT,
    TERMINAL_MIN_HEIGHT,
    toggleTerminal,
    visibleLines,
    type LineFilters,
} from '@/lib/terminal'
import { runSettled } from '@/lib/status'
import type { LogLevel } from '@/lib/status'
import { said } from '@/lib/refusal'

export const HIDE_TERMINAL_LABEL = LABELS.terminal.hide
export const RESIZE_TERMINAL_LABEL = LABELS.terminal.resize
export const COPY_LINES_LABEL = LABELS.terminal.copy_lines
export const DOWNLOAD_LOG_LABEL = LABELS.terminal.download
export const MATCH_LABEL = LABELS.terminal.match_filter
export const NEWEST_LABEL = LABELS.terminal.newest

/** What the step select's "no step at all" row is worth, which is every step. */
const EVERY_STEP = ''

/** How many pages of `$logs` a download walks before it stops asking. Fifty of them is 25,000 lines. */
const DOWNLOAD_PAGE_LIMIT = 50

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
 * ladder, so every control in it is a library control with nothing re-inked.
 *
 * IT FOLLOWS THE TAIL UNTIL SOMEBODY SCROLLS UP, which is `lib/preferences`' own setting and
 * the same rule the step's log pane is written to: a console that jumped to the bottom while
 * somebody was reading what failed would be unreadable during exactly the run that matters.
 *
 * A STEP'S NAME OPENS THAT STEP IN THE PANEL. A run-level line belongs to no step, so its `run`
 * is a plain label rather than a control.
 *
 * It is sokkel-ui's `Dock` holding sokkel-ui's `LogView`: the dock's top edge is the drag, at
 * the height `lib/terminal` holds, the tools stand in its head, and the filters and their count in
 * its bar under the head.
 */
export function RunTerminal({
    state,
    runId,
    step: chosenStep = null,
    onSelectStep,
}: {
    state: RunDetailState
    runId: string
    /** The step chosen on the graph, which narrows the lines to it. */
    step?: string | null
    /** What a line's step prefix does: select that step and open it in the panel. */
    onSelectStep: (step: string) => void
}) {
    const height = useStore(terminalHeight)
    const following = useStore(followTails)

    const [filters, setFilters] = useState<LineFilters>(EVERY_LINE)
    useEffect(() => {
        // The graph is the other place a step is chosen, and the filter follows it.
        // oxlint-disable-next-line react/set-state-in-effect
        setFilters((current) => ({ ...current, step: chosenStep ?? '' }))
    }, [chosenStep])
    const [saving, setSaving] = useState(false)

    // The lines carry the attempt that wrote them and no label; the attempts on the same stream
    // carry theirs, so which element a line belongs to is a join over what is already held. The
    // search reads it too, because it is drawn on the line.
    const labels = useMemo(() => itemLabels(state), [state])
    const shown = useMemo(() => visibleLines(state.logs, filters, labels), [state.logs, filters, labels])
    const drawn = useMemo(() => countLines(shown), [shown])
    const held = useMemo(() => countLines(state.logs), [state.logs])
    const countNote = lineCount(drawn, held)
    const steps = stepChoices(state)

    // Each drawn line, and the entry it was drawn from, which is what its source opens.
    const { lines, entryOf } = useMemo(() => {
        const entries = new Map<LogLine, LogEntryOut>()
        const drawnLines = shown.map((entry) => {
            const step = stepOf(entry)
            const line: LogLine = {
                at: formatClock(entry.created_at),
                level: entry.level as LineLevel,
                source: step ?? LABELS.word.run.term,
                sourceLink: step !== null,
                item: itemOfEntry(labels, entry.step_attempt_id) ?? undefined,
                text: entry.message,
                fields: fieldsText(entry.fields) ?? undefined,
            }
            entries.set(line, entry)
            return line
        })
        return { lines: drawnLines, entryOf: entries }
    }, [shown, labels])

    const openSource = (_source: string, line: LogLine) => {
        const entry = entryOf.get(line)
        const step = entry === undefined ? null : stepOf(entry)
        if (step !== null) onSelectStep(step)
    }

    const copy = () => {
        void navigator.clipboard?.writeText(copyText(shown)).then(
            () => toast.success(counted(drawn, LABELS.terminal.copied)(String(drawn))),
            () => toast.error(LABELS.runs.clipboard_refused),
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
                const url = URL.createObjectURL(
                    new Blob([asNdjson(collected)], { type: 'application/x-ndjson' }),
                )
                const anchor = document.createElement('a')
                anchor.href = url
                anchor.download = downloadName(runId)
                // In the document, because a click on an anchor no document holds does nothing.
                document.body.append(anchor)
                anchor.click()
                anchor.remove()
                URL.revokeObjectURL(url)
                toast.success(counted(collected.length, LABELS.terminal.saved)(String(collected.length)))
            },
            (error: unknown) => {
                setSaving(false)
                toast.error(error instanceof ApiError ? said(error.problem) : LABELS.refusal.no_answer.term)
            },
        )
    }

    return (
        <Dock
            aria-label={LABELS.terminal.name}
            className="@container"
            title={
                <span className="flex items-center gap-2">
                    <ICONS.terminal className="size-4 shrink-0" aria-hidden />
                    {LABELS.terminal.heading}
                </span>
            }
            bar={
                <>
                    {/* A dock narrower than 48rem has no room for the count. */}
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                        <FilterChip
                            facet={LABELS.terminal.level_facet}
                            options={LEVELS.filter((level) => level !== EVERY_LINE.level).map((level) => ({
                                value: level,
                                label: LABELS.terminal.level[level],
                            }))}
                            {...oneChosen(
                                filters.level === EVERY_LINE.level ? '' : filters.level,
                                (level) => {
                                    setFilters((current) => ({
                                        ...current,
                                        level: level === '' ? EVERY_LINE.level : (level as LogLevel),
                                    }))
                                },
                            )}
                            words={filterWords(LABELS.terminal.level[EVERY_LINE.level])}
                        />

                        <FilterChip
                            facet={LABELS.terminal.step_facet}
                            options={steps.map((step) => ({
                                value: step,
                                label: step,
                                row: <span className="font-mono">{step}</span>,
                            }))}
                            value={
                                filters.step === EVERY_STEP ? undefined : (
                                    <span className="font-mono">{filters.step}</span>
                                )
                            }
                            {...oneChosen(filters.step, (step) => {
                                setFilters((current) => ({ ...current, step }))
                            })}
                            words={filterWords(LABELS.terminal.every_step)}
                        />

                        <SearchField
                            className="min-w-0 flex-1 @3xl:max-w-48"
                            shortcut={false}
                            value={filters.match}
                            onChange={(match) => {
                                setFilters((current) => ({ ...current, match }))
                            }}
                            placeholder={LABELS.terminal.match_placeholder}
                            label={MATCH_LABEL}
                            words={SEARCH_WORDS}
                        />
                    </div>
                    {countNote !== null && (
                        <span className="ml-auto text-xs whitespace-nowrap text-muted-foreground @max-3xl:hidden">
                            {countNote}
                        </span>
                    )}
                </>
            }
            tools={
                <>
                    <IconButton
                        label={COPY_LINES_LABEL}
                        size="icon-sm"
                        disabled={shown.length === 0}
                        onClick={copy}
                    >
                        <ICONS.copy aria-hidden />
                    </IconButton>
                    <IconButton
                        label={DOWNLOAD_LOG_LABEL}
                        size="icon-sm"
                        disabled={saving}
                        onClick={download}
                    >
                        <ICONS.download aria-hidden />
                    </IconButton>
                    <IconButton label={HIDE_TERMINAL_LABEL} size="icon-sm" onClick={toggleTerminal}>
                        <ICONS.close_panel aria-hidden />
                    </IconButton>
                </>
            }
            size={height}
            onSizeChange={setTerminalHeight}
            minSize={TERMINAL_MIN_HEIGHT}
            maxSize={TERMINAL_MAX_HEIGHT}
            defaultSize={TERMINAL_DEFAULT_HEIGHT}
            words={{ resize: RESIZE_TERMINAL_LABEL }}
        >
            <div className="flex h-full flex-col">
                <LogView
                    lines={lines}
                    follow={following}
                    wrap
                    numbered={false}
                    framed={false}
                    query={filters.match.trim()}
                    onSource={openSource}
                    words={{ jump: NEWEST_LABEL }}
                    empty={emptyNote(filters, state.logs.length, runSettled(state.run?.status ?? null))}
                    className="flex-1"
                />
                {/* The one place "is anything still coming" is answered: the status bar
                        says nothing once a run has settled, and the answer belongs where the
                        lines it is about are. */}
                {state.stream === 'ended' && (
                    <p className="shrink-0 bg-terminal px-3 pb-2 font-mono text-xs text-terminal-faint">
                        {endNote(state.run?.status ?? null)}
                    </p>
                )}
            </div>
        </Dock>
    )
}
