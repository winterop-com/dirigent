import { BookOpen, ChevronDown, FilePlus2, Plus, RefreshCw } from 'lucide-react'
import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { Chip } from '@/components/ds/Chip'
import { Code } from '@/components/ds/Code'
import { PageHeader } from '@/components/ds/PageHeader'
import { SearchField } from '@/components/ds/SearchField'
import { SectionHeading } from '@/components/ds/SectionHeading'
import { Surface } from '@/components/ds/Surface'
import { MiniGraph } from '@/components/graph/MiniGraph'
import { Instant } from '@/components/Instant'
import { TagFilter } from '@/components/list/TagFilter'
import { PageState } from '@/components/PageState'
import { Refusable } from '@/components/Refusable'
import { StatusChip } from '@/components/run/StatusChip'
import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useMayWrite } from '@/hooks/use-may-write'
import { useRead } from '@/hooks/use-read'
import { ICONS } from '@/lib/icons'
import { headingOf, oneLine } from '@/lib/identity'
import { counted, LABELS } from '@/lib/labels'
import { NEW_PIPELINE_PATH } from '@/lib/nav'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import {
    EXAMPLES_SHOWN,
    emptyNote,
    failedStepOf,
    importanceMark,
    readAllPipelines,
    readTagsOffered,
    retirement,
    sourceKinds,
    splitListing,
    tagsFromQuery,
    type PipelineOut,
} from '@/lib/pipelines'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { cn } from '@/lib/utils'

/**
 * The picker over the installed starters, mounted only once somebody asks for it.
 *
 * It reads the whole corpus and carries the copy rule, and a reader who never starts from a
 * starter pays for neither.
 */
const StarterPicker = lazy(() =>
    import('@/components/examples/StarterPicker').then((module) => ({ default: module.StarterPicker })),
)

export const NEW_PIPELINE_LABEL = LABELS.pipelines.new

export const FROM_FILE_LABEL = LABELS.pipelines.from_file

export const FROM_STARTER_LABEL = LABELS.pipelines.from_starter

/** The address flag that opens the whole examples band. */
const ALL_EXAMPLES = 'examples'

/**
 * Every pipeline this instance holds, each led by its shape, the person's own apart from the
 * shipped examples.
 *
 * THE LISTING IS READ WHOLE. Splitting the two lists and putting the examples that ran first
 * needs every row, so the walk reads the listing in a few large pages rather than paging as
 * somebody scrolls. The tag filter is the server's and re-reads it; the search box narrows what
 * was read.
 *
 * A ROW IS THE LINK TO THE PIPELINE'S PAGE, and draws no panel and no arrow.
 */
export function Pipelines() {
    const navigate = useNavigate()
    const [needle, setNeedle] = useState('')
    const [asked, setAsked] = useSearchParams()
    const filePicker = useRef<HTMLInputElement | null>(null)
    const [picking, setPicking] = useState(false)

    const tags = useMemo(() => tagsFromQuery(asked), [asked])
    const allExamples = asked.get(ALL_EXAMPLES) === 'all'
    const setTags = useCallback(
        (next: readonly string[]) => {
            const query = new URLSearchParams(asked)
            query.delete('tag')
            for (const tag of next) query.append('tag', tag)
            setAsked(query, { replace: true })
        },
        [asked, setAsked],
    )
    const toggleExamples = useCallback(() => {
        const query = new URLSearchParams(asked)
        if (allExamples) query.delete(ALL_EXAMPLES)
        else query.set(ALL_EXAMPLES, 'all')
        setAsked(query, { replace: true })
    }, [allExamples, asked, setAsked])

    const listing = useRead(useCallback(() => readAllPipelines(tags), [tags]))
    const rows = useMemo(() => listing.value ?? [], [listing.value])
    const lists = useMemo(() => splitListing(narrow(rows, needle)), [needle, rows])
    const offered = useRead(readTagsOffered)
    const write = useMayWrite()
    const mayWrite = write.may
    const { again } = listing

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

    useEffect(() => {
        return registerActions([
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
                          id: 'pipelines:from-starter',
                          title: LABELS.pipelines.palette.from_starter,
                          group: LIST_GROUP,
                          screen: true,
                          icon: BookOpen,
                          keywords: ['example', 'copy', 'corpus', 'recipe'],
                          run: () => {
                              setPicking(true)
                          },
                      },
                      {
                          id: 'pipelines:from-file',
                          title: LABELS.pipelines.palette.from_file,
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
                title: LABELS.pipelines.palette.reload,
                group: LIST_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload'],
                run: again,
            },
        ])
    }, [again, mayWrite, navigate])

    const shown = lists.own.length + lists.examples.length
    const examples = allExamples ? lists.examples : lists.examples.slice(0, EXAMPLES_SHOWN)

    return (
        <>
            <PageHeader
                title={LABELS.screen.pipelines.name}
                aside={
                    <>
                        <ApiChip tag="pipelines" />
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
                                    className="rounded-r-none"
                                    aria-label={NEW_PIPELINE_LABEL}
                                    disabled={!write.may}
                                    title={write.why ?? NEW_PIPELINE_LABEL}
                                    onClick={() => {
                                        void navigate(NEW_PIPELINE_PATH)
                                    }}
                                >
                                    {LABELS.action.new}
                                </Button>
                            </Refusable>
                            <DropdownMenu>
                                <DropdownMenuTrigger
                                    render={
                                        <Button
                                            className="rounded-l-none border-l border-primary-foreground/20 px-1.5"
                                            aria-label={LABELS.pipelines.more_ways}
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
                                            setPicking(true)
                                        }}
                                    >
                                        <BookOpen aria-hidden />
                                        {FROM_STARTER_LABEL}
                                    </DropdownMenuItem>
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

            <div className="mb-6 flex flex-wrap items-center gap-2">
                <SearchField value={needle} label={LABELS.pipelines.search} onChange={setNeedle} />
                <TagFilter chosen={tags} offered={offered.value ?? []} onChange={setTags} />
            </div>

            <PageState
                loading={listing.value === null && listing.problem === null}
                problem={listing.problem}
                empty={shown === 0}
                emptyMessage={emptyNote(rows.length, tags)}
            >
                <div className="flex flex-col gap-9" data-testid="pipeline-lists">
                    {lists.own.length > 0 && (
                        <section aria-labelledby="own-pipelines" className="flex flex-col gap-3">
                            <SectionHeading id="own-pipelines" aside={<Count n={lists.own.length} />}>
                                {LABELS.pipelines.lists.own}
                            </SectionHeading>
                            <Surface inset={false} as="div">
                                {lists.own.map((row) => (
                                    <PipelineRow key={row.id} row={row} dense={false} />
                                ))}
                            </Surface>
                        </section>
                    )}
                    {lists.examples.length > 0 && (
                        <section aria-labelledby="example-pipelines" className="flex flex-col gap-3">
                            <SectionHeading
                                id="example-pipelines"
                                aside={
                                    <>
                                        <Count n={lists.examples.length} />
                                        {lists.examples.length > EXAMPLES_SHOWN && (
                                            <button
                                                type="button"
                                                className="rounded-sm text-muted-foreground underline-offset-2 outline-none hover:text-foreground hover:underline focus-visible:ring-2 focus-visible:ring-ring"
                                                aria-expanded={allExamples}
                                                onClick={toggleExamples}
                                            >
                                                {allExamples
                                                    ? LABELS.pipelines.lists.fewer_examples
                                                    : LABELS.pipelines.lists.all_examples(
                                                          String(lists.examples.length),
                                                      )}
                                            </button>
                                        )}
                                    </>
                                }
                            >
                                {LABELS.pipelines.lists.examples}
                            </SectionHeading>
                            <Surface tone="recessed" inset={false} as="div">
                                {examples.map((row) => (
                                    <PipelineRow key={row.id} row={row} dense />
                                ))}
                            </Surface>
                        </section>
                    )}
                </div>
            </PageState>

            {picking && (
                <Suspense fallback={null}>
                    <StarterPicker
                        open
                        onOpenChange={setPicking}
                        onChoose={(document) => {
                            void navigate(NEW_PIPELINE_PATH, { state: { document } })
                        }}
                    />
                </Suspense>
            )}
        </>
    )
}

/** How many rows a list holds, beside its heading. */
function Count({ n }: { n: number }) {
    return <span className="text-xs text-muted-foreground tabular-nums">{String(n)}</span>
}

/**
 * The rows whose code, name, description or tags carry what was typed.
 *
 * The tags are in the haystack so a corpus can be found by what it is for without reaching for
 * the filter beside the box.
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
 * One pipeline: its shape, its title and code, the first sentence of its description, and what
 * fires it and how it last ran where those exist.
 *
 * A dense row is an example's, on the recessed band: one line of description, and its facts
 * beside the words rather than under them.
 */
function PipelineRow({ row, dense }: { row: PipelineOut; dense: boolean }) {
    const heading = headingOf(row)
    const retired = retirement(row)
    const mark = importanceMark(row.importance)
    const sources = sourceKinds(row)
    const sentence = row.description === null ? null : oneLine(row.description)
    const facts = (
        <div className={cn('flex flex-wrap items-center gap-x-3.5 gap-y-2', !dense && 'mt-2.5')}>
            {row.schedules > 0 && (
                <Chip icon={ICONS.schedule}>
                    {`${String(row.schedules)} ${counted(row.schedules, LABELS.word.schedule.count)}`}
                </Chip>
            )}
            {sources.map((kind) => (
                <Chip key={kind} icon={ICONS.source}>
                    {kind}
                </Chip>
            ))}
            {row.active_runs > 0 ? (
                <StatusChip status="running" label={LABELS.word.in_flight.counted(String(row.active_runs))} />
            ) : (
                row.last_run !== null && (
                    <span className="inline-flex items-center gap-2 text-xs">
                        <StatusChip status={row.last_run.status} />
                        <Instant
                            at={row.last_run.finished_at ?? row.last_run.started_at}
                            className="text-muted-foreground"
                        />
                    </span>
                )
            )}
        </div>
    )
    const hasFacts = row.schedules > 0 || sources.length > 0 || row.active_runs > 0 || row.last_run !== null
    return (
        <Link
            to={`/pipelines/${encodeURIComponent(row.code)}`}
            className={cn(
                'control-link flex flex-wrap items-center border-t border-border outline-none first:border-t-0 hover:bg-muted focus-visible:bg-muted',
                dense ? 'min-h-16 gap-x-7 gap-y-2 px-5 py-2.5' : 'min-h-22 gap-x-7 gap-y-3 px-5 py-4',
                retired !== null && 'opacity-60',
            )}
            data-testid="pipeline-row"
        >
            <div className={cn('flex w-59 shrink-0 items-center overflow-hidden', dense ? 'h-10' : 'h-13')}>
                <MiniGraph
                    steps={row.shape}
                    failed={failedStepOf(row)}
                    width={236}
                    height={dense ? 40 : 52}
                />
            </div>
            <div className="min-w-0 flex-[999_1_320px]">
                <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-0.5">
                    <span
                        className={cn(
                            'min-w-0 truncate',
                            dense ? 'text-base font-medium' : 'text-title font-semibold',
                            !heading.named && 'font-mono',
                        )}
                        title={heading.title}
                    >
                        {heading.title}
                    </span>
                    {heading.code !== null && <Code value={heading.code} />}
                    {mark !== null && (
                        <Chip tone="critical" title={mark.title}>
                            {mark.label}
                        </Chip>
                    )}
                    {retired !== null && (
                        <Chip tone="dashed" title={LABELS.pipelines.deactivated.explained}>
                            {retired}
                        </Chip>
                    )}
                </div>
                {sentence !== null && (
                    <p
                        className={cn(
                            'text-sm text-muted-foreground',
                            dense ? 'mt-0.5 truncate text-xs' : 'mt-1',
                        )}
                        title={dense ? sentence : undefined}
                    >
                        {sentence}
                    </p>
                )}
                {!dense && hasFacts && facts}
            </div>
            {dense && hasFacts && <div className="flex-[0_1_auto]">{facts}</div>}
        </Link>
    )
}
