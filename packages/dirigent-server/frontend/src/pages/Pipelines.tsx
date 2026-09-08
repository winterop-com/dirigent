import { ChevronDown, Clock, FilePlus2, Plus, RefreshCw, Webhook } from 'lucide-react'
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { ListTable, type Column } from '@/components/list/ListTable'
import { TagFilter } from '@/components/list/TagFilter'
import { PageHeader, PageState } from '@/components/PageState'
import { StatusDot } from '@/components/run/StatusChip'
import { TagChips } from '@/components/TagChips'
import { Refusable } from '@/components/Refusable'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { useRead } from '@/hooks/use-read'
import { formatInstant } from '@/lib/format'
import { headingOf, oneLine } from '@/lib/identity'
import { NEW_PIPELINE_PATH } from '@/lib/nav'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { fillPanel, openPanelTab, type PanelTab } from '@/lib/panels'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import {
    byTitle,
    emptyNote,
    lastRunView,
    readPipelines,
    readTagsOffered,
    retirement,
    tagsFromQuery,
    triggerSummary,
    type PipelineOut,
} from '@/lib/pipelines'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { statusLabel, statusTokens } from '@/lib/status'
import { cn } from '@/lib/utils'

const pipelineId = (row: PipelineOut) => row.id

/**
 * The pane a chosen row opens, which nothing on this screen needs until a row is chosen.
 *
 * It carries the schema reader, the markdown lexer and the requirements check, and this screen
 * is in the entry chunk every reader pays for.
 */
const PipelinePreview = lazy(() =>
    import('@/components/pipelines/PipelinePreview').then((module) => ({ default: module.PipelinePreview })),
)

/** Which tab of the right panel a chosen row opens. */
const PREVIEW_TAB = 'pipeline'

export const NEW_PIPELINE_LABEL = 'New pipeline'

export const FROM_FILE_LABEL = 'From file…'

/**
 * Every pipeline this instance holds, in the order the titles on screen read in.
 *
 * SEARCHING IS A SQUINT AT THE ROWS ALREADY ON SCREEN, not a question put to the server, and
 * the foot says how many rows those are, so what it is narrowing is never in doubt. THE TAG
 * FILTER IS THE OTHER THING: `GET /pipelines` takes it, so choosing a tag re-reads the listing
 * and pages through what it narrowed to, and choosing a second one narrows again.
 *
 * THE TAGS LIVE IN THE ADDRESS. A narrowed listing is a link somebody sends, so the query is
 * the filter's only state and a chip writes to it; it replaces rather than pushes, because a
 * filter somebody is assembling is one destination and not five.
 *
 * A ROW OPENS BESIDE THE TABLE; ITS TITLE OPENS THE EDITOR. Choosing a row is a request to read
 * that pipeline, and reading it is what the panel is for -- the version, what it takes, what it
 * reaches, how it has been running. Going to the editor is a second, louder intent, and the
 * title is the link that carries it.
 *
 * A ROW REGISTERS NOTHING WITH THE PALETTE. A screen registers what only it can do, and a
 * listing of fifty pipelines that each contributed a row would bury every other action in the
 * app under its own contents.
 */
export function Pipelines() {
    const navigate = useNavigate()
    const [needle, setNeedle] = useState('')
    const [asked, setAsked] = useSearchParams()
    const filePicker = useRef<HTMLInputElement | null>(null)
    const [chosen, setChosen] = useState<PipelineOut | null>(null)

    // Held against the address, so the read below is asked again only when the filter changed.
    const tags = useMemo(() => tagsFromQuery(asked), [asked])
    const setTags = useCallback(
        (next: readonly string[]) => {
            const query = new URLSearchParams(asked)
            query.delete('tag')
            for (const tag of next) query.append('tag', tag)
            setAsked(query, { replace: true })
        },
        [asked, setAsked],
    )
    const addTag = useCallback(
        (tag: string) => {
            if (!tags.includes(tag)) setTags([...tags, tag])
        },
        [setTags, tags],
    )

    const read = useCallback((after: string | null) => readPipelines(after, tags), [tags])
    const { state, more, reload } = usePaged(read, pipelineId)

    const shown = useMemo(() => narrow(state.rows, needle).toSorted(byTitle), [needle, state.rows])
    // The tags on offer are read once and stay put, because choosing one narrows the listing:
    // a menu built from the rows that came back would lose the tags somebody adds next.
    const offered = useRead(readTagsOffered)
    const columns = useMemo(() => pipelineColumns(addTag), [addTag])
    const write = useMayWrite()
    const mayWrite = write.may

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [state.rows.length])

    useEffect(() => {
        return registerActions([
            // A row this account's role would be refused is a row the palette does not offer.
            ...(mayWrite
                ? [
                      {
                          id: 'pipelines:new',
                          title: NEW_PIPELINE_LABEL,
                          group: LIST_GROUP,
                          screen: true,
                          icon: Plus,
                          keywords: ['create', 'draft', 'start', 'editor'],
                          run: () => {
                              void navigate(NEW_PIPELINE_PATH)
                          },
                      },
                      {
                          id: 'pipelines:from-file',
                          title: 'New pipeline from a file',
                          group: LIST_GROUP,
                          screen: true,
                          icon: FilePlus2,
                          keywords: ['upload', 'yaml', 'apply', 'import'],
                          run: () => {
                              filePicker.current?.click()
                          },
                      },
                  ]
                : []),
            {
                id: 'pipelines:reload',
                title: 'Read the pipelines listing again',
                group: LIST_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload'],
                run: reload,
            },
        ])
    }, [mayWrite, navigate, reload])

    // The panel is the screen's, and it holds the row that was chosen until another one is.
    const tabs = useMemo<PanelTab[]>(() => {
        if (chosen === null) return []
        return [
            {
                id: PREVIEW_TAB,
                label: 'Pipeline',
                render: () => (
                    <Suspense fallback={<PanelReading />}>
                        <PipelinePreview key={chosen.code} pipeline={chosen} />
                    </Suspense>
                ),
            },
        ]
    }, [chosen])

    useEffect(() => fillPanel(tabs, { screen: 'pipelines' }), [tabs])

    return (
        <>
            <PageHeader
                title="Pipelines"
                aside={
                    <>
                        <ApiChip tag="pipelines" />
                        {summary(shown.length, state.rows.length) !== null && (
                            <span className="text-muted-foreground text-xs">
                                {summary(shown.length, state.rows.length)}
                            </span>
                        )}
                        <input
                            ref={filePicker}
                            type="file"
                            accept=".yaml,.yml,.json,text/yaml,application/json"
                            className="hidden"
                            aria-label={FROM_FILE_LABEL}
                            onChange={(event) => {
                                const file = event.target.files?.[0]
                                event.target.value = ''
                                if (file === undefined) return
                                void file.text().then((document) => {
                                    void navigate(NEW_PIPELINE_PATH, { state: { document } })
                                })
                            }}
                        />
                        <div className="flex">
                            <Refusable why={write.why}>
                                <Button
                                    size="sm"
                                    className="rounded-r-none"
                                    aria-label={NEW_PIPELINE_LABEL}
                                    disabled={!write.may}
                                    title={write.why ?? NEW_PIPELINE_LABEL}
                                    onClick={() => {
                                        void navigate(NEW_PIPELINE_PATH)
                                    }}
                                >
                                    New
                                </Button>
                            </Refusable>
                            <DropdownMenu>
                                <DropdownMenuTrigger
                                    render={
                                        <Button
                                            size="sm"
                                            className="border-primary-foreground/20 rounded-l-none border-l px-1.5"
                                            aria-label="More ways to start a pipeline"
                                            disabled={!write.may}
                                            title={write.why}
                                        >
                                            <ChevronDown aria-hidden />
                                        </Button>
                                    }
                                />
                                <DropdownMenuContent align="end">
                                    <DropdownMenuItem
                                        onClick={() => {
                                            filePicker.current?.click()
                                        }}
                                    >
                                        <FilePlus2 aria-hidden />
                                        {FROM_FILE_LABEL}
                                    </DropdownMenuItem>
                                </DropdownMenuContent>
                            </DropdownMenu>
                        </div>
                    </>
                }
            />

            <div className="mb-4 flex flex-wrap items-center gap-2">
                <Input
                    className="w-56"
                    value={needle}
                    onChange={(event) => {
                        setNeedle(event.target.value)
                    }}
                    placeholder="Search pipelines"
                    aria-label="Search pipelines by code, name or tag"
                />
                <TagFilter chosen={tags} offered={offered.value ?? []} onChange={setTags} />
            </div>

            <PageState
                loading={!state.read}
                problem={state.problem}
                empty={shown.length === 0}
                emptyMessage={emptyNote(state.rows.length, tags)}
            >
                <ListTable
                    columns={columns}
                    rows={shown}
                    rowKey={pipelineId}
                    onSelect={(row) => {
                        setChosen(row)
                        openPanelTab(PREVIEW_TAB)
                    }}
                    selected={(row) => row.id === chosen?.id}
                    rowClassName={(row) => (retirement(row) === null ? undefined : 'opacity-60')}
                    reading={state.reading}
                    next={state.next}
                    onMore={more}
                    noun="pipelines"
                />
            </PageState>

        </>
    )
}

/** What stands in the panel while the pane's own chunk is being fetched. */
function PanelReading() {
    return (
        <div className="p-4">
            <PageState loading problem={null} empty={false}>
                {null}
            </PageState>
        </div>
    )
}

/**
 * The rows whose code, name, description or tags carry what was typed.
 *
 * The tags are in the haystack so a corpus can be found by what it is for without reaching for
 * the filter beside the box: typing `climate` finds the climate pipelines either way.
 */
function narrow(rows: readonly PipelineOut[], needle: string): PipelineOut[] {
    const wanted = needle.trim().toLowerCase()
    if (wanted === '') return [...rows]
    return rows.filter((row) =>
        `${row.code} ${row.name ?? ''} ${row.description ?? ''} ${row.tags.join(' ')}`
            .toLowerCase()
            .includes(wanted),
    )
}

/**
 * How many rows are on screen out of how many were read, or nothing when they are the same
 * number -- which the foot of the table already says, and the status bar says too.
 */
function summary(shown: number, loaded: number): string | null {
    if (shown === loaded) return null
    return `${String(shown)} of ${String(loaded)}`
}

/**
 * The columns, which differ between readers only by what a tag chip does when it is clicked.
 *
 * A CHIP ON A ROW NARROWS THE LISTING. It is the same filter the bar holds, reached from the
 * row that shows what to reach for, so clicking one adds it rather than replacing what is there.
 */
function pipelineColumns(onTag: (tag: string) => void): Column<PipelineOut>[] {
    return [
        {
            id: 'pipeline',
            header: 'Pipeline',
            // HALF THE TABLE IS THE IDENTITY'S, whatever else the row wears: `max-w-0` is what
            // lets the cell truncate, and the floor beside it is what stops anything beside it
            // bidding the title down to an ellipsis.
            className: 'w-full max-w-0 lg:min-w-[50cqi]',
            cell: (row) => {
                const retired = retirement(row)
                const heading = headingOf(row)
                return (
                    <div className="min-w-0">
                        <span className="flex items-center gap-2">
                            <Link
                                className={cn(
                                    // Cut with the whole of it on hover in the table, and wrapped
                                    // on a card, where there is room and no pointer to hover with.
                                    'truncate font-semibold hover:underline',
                                    'max-lg:overflow-visible max-lg:whitespace-normal',
                                    !heading.named && 'font-mono',
                                )}
                                to={`/pipelines/${encodeURIComponent(row.code)}`}
                                title={heading.title}
                            >
                                {heading.title}
                            </Link>
                            {retired !== null && (
                                <span
                                    className="border-border text-faint rounded-sm border px-1.5 text-xs"
                                    title="deactivated: its schedules are paused and it cannot be run"
                                >
                                    {retired}
                                </span>
                            )}
                        </span>
                        <p className="flex items-center gap-2 text-xs">
                            {heading.code !== null && <span className="text-muted-foreground font-mono">{heading.code}</span>}
                            {row.description !== null && (
                                <span className="text-muted-foreground min-w-0 flex-1 truncate" title={oneLine(row.description)}>
                                    {oneLine(row.description)}
                                </span>
                            )}
                        </p>
                    </div>
                )
            },
        },
        {
            id: 'tags',
            header: 'Tags',
            // No width of its own: the cell's own bound is what stops the column, and the lead
            // column's `w-full` takes everything the chips did not need.
            cell: (row) => <TagChips tags={row.tags} onSelect={onTag} />,
        },
        {
            id: 'triggers',
            header: 'Triggers',
            cell: (row) =>
                row.schedules === 0 && row.webhooks === 0 ? null : (
                    <span className="text-muted-foreground flex items-center gap-3 text-xs" title={triggerSummary(row)}>
                        {row.schedules > 0 && (
                            <span className="flex items-center gap-1">
                                <Clock className="size-3" aria-hidden />
                                {String(row.schedules)}
                            </span>
                        )}
                        {row.webhooks > 0 && (
                            <span className="flex items-center gap-1">
                                <Webhook className="size-3" aria-hidden />
                                {String(row.webhooks)}
                            </span>
                        )}
                    </span>
                ),
        },
        {
            id: 'last-run',
            header: 'Last run',
            // One line, and no wider than that line: what this column says is short, and every
            // pixel it does not need is the title's.
            className: 'whitespace-nowrap',
            cell: (row) => <LastRunCell row={row} />,
        },
    ]
}

/** How the newest run of a pipeline went, or that it has never had one. */
function LastRunCell({ row }: { row: PipelineOut }) {
    const view = lastRunView(row.last_run)
    if (row.active_runs > 0) {
        return (
            <span
                className="status-chip font-medium"
                data-status="running"
                data-live="true"
                style={statusTokens('running') as CSSProperties}
            >
                <span className="status-dot" aria-hidden />
                {row.active_runs === 1 ? 'running' : `${String(row.active_runs)} running`}
            </span>
        )
    }
    if (view === null || row.last_run === null) return <span className="text-faint text-xs">never run</span>
    return (
        // Bounded, because half the table is the identity's and this column's own words are
        // what it gives back: the instant stands and what follows it is cut with the whole of
        // it on hover.
        <span className="flex min-w-0 items-center gap-1.5 text-xs lg:max-w-[14cqi]">
            <StatusDot status={view.status} />
            <Link
                className="shrink-0 hover:underline"
                to={`/runs/${row.last_run.id}`}
                title={formatInstant(view.instant)}
            >
                {view.when}
            </Link>
            {view.failedStep === null ? (
                <span className="text-faint truncate" title={statusLabel(view.status)}>
                    {statusLabel(view.status)}
                </span>
            ) : (
                <span className="text-muted-foreground truncate" title={`at ${view.failedStep}`}>
                    at {view.failedStep}
                </span>
            )}
        </span>
    )
}
