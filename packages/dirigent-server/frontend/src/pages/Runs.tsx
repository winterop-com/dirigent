import { ArrowUp, CircleX, Clock, FilterX, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { Choice } from '@/components/list/Choice'
import { ListTable, type Column } from '@/components/list/ListTable'
import { TagFilter } from '@/components/list/TagFilter'
import { PageHeader, PageState } from '@/components/PageState'
import { StatusChip } from '@/components/run/StatusChip'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useStore } from '@/hooks/use-store'
import { refreshSeconds } from '@/lib/refresh'
import { usePaged } from '@/hooks/use-paged'
import { useRead } from '@/hooks/use-read'
import { elapsedBetween, formatDuration, formatInstant, formatRelative } from '@/lib/format'
import { headingOf } from '@/lib/identity'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { readPipelineNames, readTagsOffered } from '@/lib/pipelines'
import {
    emptyNote,
    EVERY_RUN,
    filtersFromQuery,
    priorityMark,
    readRuns,
    triggerSummary,
    WINDOWS,
    type RunFilters,
    type RunOut,
} from '@/lib/runs'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { RUN_STATUSES, statusLabel } from '@/lib/status'
import { cn } from '@/lib/utils'

/** How long a pipeline code is left alone after a keystroke before it becomes a request. */
const TYPING_MS = 300

const runId = (run: RunOut) => run.id


/**
 * Every run this instance has, newest first.
 *
 * WHAT IS FILTERED HERE IS WHAT THE SERVER FILTERS. `GET /runs` narrows by pipeline, by status,
 * by how far back to look and by the tags the run's pipeline wears, so the bar offers those
 * four. A fifth control would narrow the rows that happen to have been loaded rather than the
 * listing, and would answer a question nobody asked as though it were the one they did.
 *
 * NO ROW WEARS A TAG. A run row already names its pipeline, and repeating that pipeline's
 * vocabulary on every run of it would be the same words down the whole column.
 *
 * NOTHING POLLS. A run's own screen holds a stream; a listing does not, because a page of fifty
 * rows re-read every few seconds is fifty rows of load for a tab nobody may be looking at.
 * Coming back to the tab re-reads the first page once, and what arrived while it was away is
 * what the pill counts.
 *
 * THE ADDRESS OPENS THE FILTERS, AND THE CONTROLS OWN THEM AFTER THAT. A number on the dashboard
 * links here narrowed the way it was counted, so the query is where this screen starts; from
 * then on the bar is what says what is filtered, and a control that rewrote the address would
 * put a history entry behind every keystroke.
 */
export function Runs() {
    const navigate = useNavigate()
    const [asked] = useSearchParams()
    const [filters, setFilters] = useState<RunFilters>(() => filtersFromQuery(asked))
    const [typed, setTyped] = useState(() => filtersFromQuery(asked).pipeline)

    // A pipeline code is filtered on the server, and a keystroke is not a question yet.
    useEffect(() => {
        const timer = setTimeout(() => {
            setFilters((current) => (current.pipeline === typed ? current : { ...current, pipeline: typed }))
        }, TYPING_MS)
        return () => {
            clearTimeout(timer)
        }
    }, [typed])

    const read = useCallback((after: string | null) => readRuns(filters, after), [filters])
    const { state, more, reload, note } = usePaged(read, runId, useStore(refreshSeconds))

    // A run row carries its pipeline's code; what that pipeline is called is read once here.
    const names = useRead(readPipelineNames)
    // The tags a run can be narrowed by are its pipeline's, so the menu is the pipelines' own.
    const offered = useRead(readTagsOffered)
    const columns = useMemo(() => runColumns(names.value), [names.value])

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [filters])

    useEffect(() => {
        return registerActions([
            {
                id: 'runs:failed',
                title: 'Show only the runs that failed',
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
                title: 'Show only the last 24 hours of runs',
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
                title: 'Clear every run filter',
                group: LIST_GROUP,
                screen: true,
                icon: FilterX,
                keywords: ['reset', 'all'],
                run: () => {
                    setTyped('')
                    setFilters(EVERY_RUN)
                },
            },
            {
                id: 'runs:reload',
                title: 'Read the runs listing again',
                group: LIST_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload'],
                run: reload,
            },
        ])
    }, [reload])

    return (
        <>
            <PageHeader
                title="Runs"
                aside={
                    <>
                        <ApiChip tag="runs" />
                        {state.fresh > 0 && (
                            <Button variant="outline" size="sm" onClick={note}>
                                <ArrowUp aria-hidden />
                                {state.fresh === 1 ? '1 new run' : `${String(state.fresh)} new runs`}
                            </Button>
                        )}
                    </>
                }
            />

            <div className="mb-4 flex flex-wrap items-center gap-2">
                <Input
                    className="w-56"
                    value={typed}
                    onChange={(event) => {
                        setTyped(event.target.value)
                    }}
                    placeholder="Search runs"
                    aria-label="Filter by pipeline"
                />
                <Choice
                    label="Status"
                    value={filters.status}
                    options={RUN_STATUSES.map((status) => ({
                        value: status,
                        label: statusLabel(status),
                        mark: <StatusChip status={status} />,
                    }))}
                    anything="Any status"
                    onChange={(status) => {
                        setFilters((current) => ({ ...current, status }))
                    }}
                />
                <Choice
                    label="Window"
                    value={filters.since}
                    options={WINDOWS.map((window) => ({ value: window, label: `Last ${window}` }))}
                    anything="All of history"
                    onChange={(since) => {
                        setFilters((current) => ({ ...current, since }))
                    }}
                />
                <TagFilter
                    chosen={filters.tags}
                    offered={offered.value ?? []}
                    onChange={(tags) => {
                        setFilters((current) => ({ ...current, tags }))
                    }}
                />
            </div>

            <PageState
                loading={!state.read}
                problem={state.problem}
                empty={state.rows.length === 0}
                emptyMessage={emptyNote(filters)}
            >
                <ListTable
                    columns={columns}
                    rows={state.rows}
                    rowKey={runId}
                    onSelect={(row) => void navigate(`/runs/${row.id}`)}
                    reading={state.reading}
                    next={state.next}
                    onMore={more}
                    noun="runs"
                />
            </PageState>
        </>
    )
}

/**
 * The columns, which differ between readers only by the pipeline names that have been read.
 *
 * The names arrive after the rows do, so a row is headed by its code until they land and by
 * its title afterwards -- which is the same answer `titleOf` gives for a pipeline with no name.
 */
function runColumns(names: ReadonlyMap<string, string | null> | null): Column<RunOut>[] {
    return [
        {
            id: 'pipeline',
            header: 'Pipeline',
            cell: (run) => <PipelineCell run={run} name={names?.get(run.pipeline) ?? null} />,
        },
        {
            id: 'status',
            header: 'Status',
            cell: (run) => (
                <span className="flex items-center gap-2">
                    <StatusChip status={run.status} />
                    <PriorityMark run={run} />
                    {run.failed_step !== null && (
                        <span className="text-muted-foreground truncate text-xs">at {run.failed_step}</span>
                    )}
                    {run.error !== null && (
                        <span className="text-muted-foreground max-w-64 truncate text-xs" title={run.error}>
                            {run.error}
                        </span>
                    )}
                </span>
            ),
        },
        {
            id: 'trigger',
            header: 'Trigger',
            cell: (run) => {
                const started = triggerSummary(run)
                return (
                    <span className="text-xs">
                        {started.kind}
                        {started.who !== null && <span className="text-faint"> · {started.who}</span>}
                    </span>
                )
            },
        },
        {
            id: 'started',
            header: 'Started',
            className: 'text-xs',
            cell: (run) => (
                <span className="text-muted-foreground" title={formatInstant(run.started_at ?? run.created_at)}>
                    {formatRelative(run.started_at ?? run.created_at)}
                </span>
            ),
        },
        {
            id: 'duration',
            header: 'Duration',
            className: 'text-right font-mono text-xs',
            cell: (run) => <Elapsed run={run} />,
        },
    ]
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

/**
 * Which pipeline a run is of, headed the way every other screen heads one.
 *
 * TITLE ELSE CODE, AND THE CODE ALWAYS ON SCREEN. The name where the pipeline has one, with the
 * code under it in mono; where it has none the code is the title and wears the mono face itself,
 * so it is never drawn twice.
 */
function PipelineCell({ run, name }: { run: RunOut; name: string | null }) {
    const heading = headingOf({ code: run.pipeline, name })
    return (
        <span className="flex min-w-0 flex-col">
            <Link
                className={cn('hover:text-primary truncate', !heading.named && 'font-mono')}
                to={`/pipelines/${encodeURIComponent(run.pipeline)}`}
            >
                {heading.title}
            </Link>
            {heading.code !== null && (
                <span className="text-muted-foreground truncate font-mono text-xs">{heading.code}</span>
            )}
        </span>
    )
}

/** How long a run took, where it has finished; a run still going has no duration to state. */
function Elapsed({ run }: { run: RunOut }) {
    const took = elapsedBetween(run.started_at, run.finished_at)
    if (took === null) return null
    return <span>{formatDuration(took)}</span>
}
