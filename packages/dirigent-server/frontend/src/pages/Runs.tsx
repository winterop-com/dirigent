import { ArrowUp, CircleX, Clock, FilterX, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { Choice } from '@/components/list/Choice'
import { TagFilter } from '@/components/list/TagFilter'
import { PageHeader } from '@/components/ds/PageHeader'
import { PageState } from '@/components/PageState'
import { PipelineRef } from '@/components/PipelineRef'
import { RunsByPipeline } from '@/components/run/RunsByPipeline'
import { DataTable, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { StatusChip } from '@winterop-com/sokkel-ui/StatusChip'
import { SearchField } from '@winterop-com/sokkel-ui/SearchField'
import { Segmented, type Segment } from '@/components/Segmented'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { useHeartbeat } from '@/hooks/use-heartbeat'
import { useStore } from '@/hooks/use-store'
import { refreshSeconds } from '@/lib/refresh'
import { usePaged } from '@/hooks/use-paged'
import { useRead } from '@/hooks/use-read'
import { elapsedBetween, formatDuration, formatInstant, formatRelative } from '@/lib/format'
import { LISTING, SEARCH_PLACEHOLDER, SEARCH_WORDS } from '@/lib/design-system'
import { counted, LABELS } from '@/lib/labels'
import { rowsRead } from '@/lib/paging'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { readPipelineNames, readTagsOffered } from '@/lib/pipelines'
import {
    GROUP_WINDOWS,
    groupedLink,
    groupWindowOf,
    readSummary,
    viewFromQuery,
    type GroupWindow,
} from '@/lib/run-summary'
import {
    emptyNote,
    EVERY_RUN,
    filtersFromQuery,
    priorityMark,
    readRuns,
    runsLink,
    startedAs,
    WINDOWS,
    type RunFilters,
    type RunOut,
} from '@/lib/runs'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { RUN_STATUSES, statusLabel } from '@/lib/status'
import { cn } from '@/lib/utils'
import { sentenceFor } from '@/lib/wording'

/** How long a pipeline code is left alone after a keystroke before it becomes a request. */
const TYPING_MS = 300

const runId = (run: RunOut) => run.id

/** The two views the screen switches between. */
type View = 'list' | 'pipeline'

const VIEWS: readonly Segment<View>[] = [
    { value: 'list', label: LABELS.runs.view.list },
    { value: 'pipeline', label: LABELS.runs.view.by_pipeline },
]

/**
 * Every run this instance has, newest first, or one row per pipeline that ran in a window.
 *
 * WHAT IS FILTERED HERE IS WHAT THE SERVER FILTERS. `GET /runs` narrows by pipeline, by status,
 * by how far back to look and by the tags the run's pipeline wears, so the bar offers those
 * four and no control narrows only the rows that happen to have been loaded. Grouped, the bar
 * asks `GET /runs/$summary` the same pipeline and tags, the status of each pipeline's newest
 * run, and the window it offers in place of how far back.
 *
 * NO ROW WEARS A TAG. The tags the bar narrows by are the pipeline's, and a run row names its
 * pipeline.
 *
 * IT IS RE-READ ON THE APP'S CADENCE. The listing pulses at whatever the refresh control is
 * set to, page one folded in at the head, and coming back to a hidden tab re-reads it at once;
 * what arrived while it was away is what the pill counts.
 *
 * THE ADDRESS OPENS THE FILTERS, AND THE CONTROLS OWN THEM AFTER THAT. A number on the dashboard
 * links here narrowed the way it was counted, so the query is where this screen starts, and a
 * link that changes the query starts it again. The list's own controls write nothing back; the
 * view and the grouped window are in the address (`?group=pipeline&window=24h`), and switching
 * either writes the filters with them.
 */
export function Runs() {
    const navigate = useNavigate()
    const [asked] = useSearchParams()
    const query = asked.toString()
    const view = viewFromQuery(asked)
    const [filters, setFilters] = useState<RunFilters>(() => filtersFromQuery(asked))
    const [typed, setTyped] = useState(() => filtersFromQuery(asked).pipeline)

    // A link to this screen with another query is a new question; the one it opened on is not.
    const opened = useRef(query)
    useEffect(() => {
        if (opened.current === query) return
        opened.current = query
        const reopened = filtersFromQuery(new URLSearchParams(query))
        setFilters(reopened)
        setTyped(reopened.pipeline)
    }, [query])

    // A pipeline code is filtered on the server, and a keystroke is not a question yet.
    useEffect(() => {
        const timer = setTimeout(() => {
            setFilters((current) => (current.pipeline === typed ? current : { ...current, pipeline: typed }))
        }, TYPING_MS)
        return () => {
            clearTimeout(timer)
        }
    }, [typed])

    // The tags a run can be narrowed by are its pipeline's, so the menu is the pipelines' own.
    const offered = useRead(readTagsOffered)

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

    useEffect(() => {
        return registerActions([
            {
                id: 'runs:failed',
                title: LABELS.runs.filter_failed,
                group: LIST_GROUP,
                screen: true,
                icon: CircleX,
                keywords: ['filter', 'broken'],
                run: () => {
                    setFilters((current) => ({ ...current, status: 'failed' }))
                },
            },
            {
                id: 'runs:day',
                title: LABELS.runs.filter_day,
                group: LIST_GROUP,
                screen: true,
                icon: Clock,
                keywords: ['filter', 'window', 'recent'],
                run: () => {
                    setFilters((current) => ({ ...current, since: '24h' }))
                },
            },
            {
                id: 'runs:clear',
                title: LABELS.runs.filter_clear,
                group: LIST_GROUP,
                screen: true,
                icon: FilterX,
                keywords: ['reset', 'all'],
                run: () => {
                    setTyped('')
                    setFilters(EVERY_RUN)
                },
            },
        ])
    }, [])

    /** Write a view into the address, with the filters as they stand so the switch keeps them. */
    const show = (next: View, window: GroupWindow) => {
        const current = { ...filters, pipeline: typed }
        void navigate(
            next === 'pipeline'
                ? groupedLink(current, window)
                : runsLink({ ...current, since: view.grouped ? window : current.since }),
        )
    }

    const bar = (
        <div className="mb-4 flex flex-wrap items-center gap-2">
            <SearchField
                placeholder={SEARCH_PLACEHOLDER}
                words={SEARCH_WORDS}
                className="w-64"
                value={typed}
                label={LABELS.runs.filter_pipeline}
                onChange={setTyped}
            />
            <Choice
                label={view.grouped ? LABELS.runs.grouped.latest_filter : LABELS.word.status}
                value={filters.status}
                options={RUN_STATUSES.map((status) => ({
                    value: status,
                    label: statusLabel(status),
                    mark: <StatusChip status={status} />,
                }))}
                anything={view.grouped ? LABELS.runs.grouped.any_latest : LABELS.runs.any_status}
                onChange={(status) => {
                    setFilters((current) => ({ ...current, status }))
                }}
            />
            {view.grouped ? (
                <Segmented
                    label={LABELS.word.window.label}
                    value={view.window}
                    options={GROUP_WINDOWS.map((window) => ({
                        value: window,
                        label: LABELS.runs.window_option(window),
                    }))}
                    onChoose={(window) => {
                        show('pipeline', window)
                    }}
                />
            ) : (
                <Choice
                    label={LABELS.word.window.label}
                    value={filters.since}
                    options={WINDOWS.map((window) => ({
                        value: window,
                        label: LABELS.runs.window_option(window),
                    }))}
                    anything={LABELS.runs.any_window}
                    onChange={(since) => {
                        setFilters((current) => ({ ...current, since }))
                    }}
                />
            )}
            <TagFilter
                chosen={filters.tags}
                offered={offered.value ?? []}
                onChange={(tags) => {
                    setFilters((current) => ({ ...current, tags }))
                }}
            />
            <div className="ml-auto">
                <Segmented
                    label={LABELS.runs.view.label}
                    value={view.grouped ? VIEWS[1].value : VIEWS[0].value}
                    options={VIEWS}
                    onChoose={(next) => {
                        show(next, view.grouped ? view.window : groupWindowOf(filters.since))
                    }}
                />
            </div>
        </div>
    )

    return view.grouped ? (
        <GroupedRuns filters={filters} window={view.window} bar={bar} />
    ) : (
        <FlatRuns filters={filters} bar={bar} />
    )
}

/** The flat list, newest first, paged. */
function FlatRuns({ filters, bar }: { filters: RunFilters; bar: ReactNode }) {
    const navigate = useNavigate()
    const read = useCallback((after: string | null) => readRuns(filters, after), [filters])
    const { state, more, reload, note } = usePaged(read, runId, useStore(refreshSeconds))

    // A run row carries its pipeline's code; what that pipeline is called is read once here.
    const names = useRead(readPipelineNames)
    const columns = useMemo(() => runColumns(names.value), [names.value])

    useEffect(() => {
        return registerActions([reloadAction(reload)])
    }, [reload])

    return (
        <>
            <PageHeader
                title={LABELS.screen.runs.name}
                lead={
                    <>
                        <ApiChip tag="runs" />
                        {state.fresh > 0 && (
                            <Button variant="outline" size="sm" onClick={note}>
                                <ArrowUp aria-hidden />
                                {counted(state.fresh, LABELS.runs.fresh)(String(state.fresh))}
                            </Button>
                        )}
                    </>
                }
            />

            {bar}

            <PageState
                loading={!state.read}
                problem={state.problem}
                empty={state.rows.length === 0}
                emptyMessage={emptyNote(filters)}
            >
                <DataTable
                    {...LISTING}
                    rowHeight="auto"
                    columns={columns}
                    rows={state.rows}
                    rowKey={runId}
                    onOpen={(row) => void navigate(`/runs/${row.id}`)}
                    hasMore={state.next !== null}
                    loading={state.reading}
                    onLoadMore={more}
                    foot={rowsRead(state.rows.length, LABELS.word.run.count, state.next !== null)}
                />
            </PageState>
        </>
    )
}

/** One row per pipeline that ran in the window, re-read on the app's cadence. */
function GroupedRuns({ filters, window, bar }: { filters: RunFilters; window: GroupWindow; bar: ReactNode }) {
    const summary = useRead(useCallback(() => readSummary(filters, window), [filters, window]))
    const { again } = summary
    useHeartbeat(again, useStore(refreshSeconds))

    useEffect(() => {
        return registerActions([reloadAction(again)])
    }, [again])

    const rows = summary.value?.pipelines ?? []
    const asked = filters.pipeline !== '' || filters.status !== '' || filters.tags.length > 0
    return (
        <>
            <PageHeader title={LABELS.screen.runs.name} lead={<ApiChip tag="runs" />} />

            {bar}

            <PageState
                loading={!summary.read}
                problem={summary.problem}
                empty={rows.length === 0}
                emptyMessage={asked ? LABELS.runs.empty_filtered : LABELS.runs.grouped.empty(window)}
            >
                <RunsByPipeline rows={rows} window={window} />
            </PageState>
        </>
    )
}

/** The palette row that reads the screen again, whichever view it is on. */
function reloadAction(run: () => void) {
    return {
        id: 'runs:reload',
        title: LABELS.runs.reload,
        group: LIST_GROUP,
        screen: true,
        icon: RefreshCw,
        keywords: ['refresh', 'reload'],
        run,
    }
}

/**
 * The columns, which differ between readers only by the pipeline names that have been read.
 *
 * The names arrive after the rows do, so a row is headed by its code until they land and by
 * its title afterwards -- which is the same answer `titleOf` gives for a pipeline with no name.
 */
function runColumns(names: ReadonlyMap<string, string | null> | null): DataColumn<RunOut>[] {
    return [
        {
            id: 'pipeline',
            header: LABELS.word.pipeline.label,
            width: 'minmax(15rem,2fr)',
            stackTitle: 'free',
            cell: (run) => <PipelineRef code={run.pipeline} name={names?.get(run.pipeline) ?? null} />,
        },
        {
            // THE STATE IS A VALUE AND WHAT WENT WRONG IS A SENTENCE. The chip holds its width --
            // the floor here is the widest of them -- and what the run has to say for itself
            // takes what is left of the column and is cut in it, with the whole of it on hover.
            // Unbounded, that sentence is the widest thing on the screen and the table it is in
            // stops fitting anywhere.
            id: 'status',
            header: LABELS.word.status,
            width: 'minmax(10rem,3fr)',
            cell: (run) => {
                const said = detailOf(run)
                return (
                    <span className="flex min-w-0 items-center gap-2 overflow-hidden">
                        <StatusChip status={run.status} />
                        <PriorityMark run={run} />
                        {said !== null && (
                            <span className="truncate text-xs text-muted-foreground" title={said}>
                                {said}
                            </span>
                        )}
                    </span>
                )
            },
        },
        {
            id: 'trigger',
            header: LABELS.word.trigger.label,
            width: 'minmax(6rem,2fr)',
            cell: (run) => {
                const started = startedAs(run)
                return (
                    <span className="block min-w-0 truncate text-xs" title={started.recorded ?? undefined}>
                        {started.said}
                    </span>
                )
            },
        },
        {
            id: 'started',
            header: LABELS.word.started.label,
            width: 'minmax(5rem,1fr)',
            cell: (run) => (
                <span
                    className="text-xs text-muted-foreground"
                    title={formatInstant(run.started_at ?? run.created_at)}
                >
                    {formatRelative(run.started_at ?? run.created_at)}
                </span>
            ),
        },
        {
            id: 'duration',
            header: LABELS.word.duration,
            width: 'minmax(4rem,1fr)',
            align: 'end',
            // A run still going has no duration to state.
            cell: (run) => {
                const took = elapsedBetween(run.started_at, run.finished_at)
                return took === null ? null : (
                    <span className="font-mono text-xs">{formatDuration(took)}</span>
                )
            },
        },
    ]
}

/**
 * What a run has to say about how it went: the step it died in, and the refusal itself, in this
 * bundle's words for its code where it has them.
 */
function detailOf(run: RunOut): string | null {
    const refusal =
        run.error_code === null
            ? run.error
            : (sentenceFor(run.error_code, run.error_params ?? {}) ?? run.error)
    const said = [run.failed_step === null ? null : LABELS.runs.failed_at(run.failed_step), refusal]
        .filter((part) => part !== null)
        .join(' ')
    return said === '' ? null : said
}

/**
 * A run's priority, where it is not the one every other run has.
 *
 * A column of "normal" would be a column saying nothing, so `normal` draws nothing at all.
 */
function PriorityMark({ run }: { run: RunOut }) {
    const mark = priorityMark(run.priority)
    if (mark === null) return null
    return <span className={cn('truncate text-xs', mark.className)}>{mark.label}</span>
}
