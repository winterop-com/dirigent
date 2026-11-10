import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { PageHeader } from '@/components/ds/PageHeader'
import { shutWith } from '@/lib/design-system'
import { SearchField } from '@winterop-com/sokkel-ui/SearchField'
import { TextLink } from '@winterop-com/sokkel-ui/TextLink'
import { Section } from '@winterop-com/sokkel-ui/Section'
import { MiniGraph } from '@/components/graph/MiniGraph'
import { Instant } from '@/components/Instant'
import { TagFilter } from '@/components/list/TagFilter'
import { PageState } from '@/components/PageState'
import { StatusChip } from '@/components/run/StatusChip'
import { useMayWrite } from '@/hooks/use-may-write'
import { useRead } from '@/hooks/use-read'
import { ICONS } from '@/lib/icons'
import { headingOf, oneLine } from '@/lib/identity'
import { SEARCH_PLACEHOLDER, SEARCH_WORDS } from '@/lib/design-system'
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
                          icon: ICONS.create,
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
                          icon: ICONS.template,
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
                          icon: ICONS.upload,
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
                icon: ICONS.refresh,
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
                primary={{
                    id: 'new',
                    label: NEW_PIPELINE_LABEL,
                    face: LABELS.action.new,
                    moreLabel: LABELS.pipelines.more_ways,
                    ...shutWith(!write.may, write.why),
                    onSelect: () => {
                        void navigate(NEW_PIPELINE_PATH)
                    },
                    more: [
                        {
                            label: FROM_STARTER_LABEL,
                            icon: <ICONS.template aria-hidden />,
                            onSelect: () => {
                                setPicking(true)
                            },
                        },
                        {
                            label: FROM_FILE_LABEL,
                            icon: <ICONS.upload aria-hidden />,
                            onSelect: () => {
                                filePicker.current?.click()
                            },
                        },
                    ],
                }}
                lead={
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
                    </>
                }
            />

            <div className="mb-6 flex flex-wrap items-center gap-2">
                <SearchField
                    placeholder={SEARCH_PLACEHOLDER}
                    words={SEARCH_WORDS}
                    className="w-64"
                    value={needle}
                    label={LABELS.pipelines.search}
                    onChange={setNeedle}
                />
                <TagFilter chosen={tags} offered={offered.value ?? []} onChange={setTags} />
            </div>

            <PageState
                loading={listing.value === null && listing.problem === null}
                problem={listing.problem}
                empty={shown === 0}
                emptyMessage={emptyNote(rows.length, tags)}
            >
                <div className="flex flex-col gap-6" data-testid="pipeline-lists">
                    {lists.own.length > 0 && (
                        <Section title={LABELS.pipelines.lists.own} meta={String(lists.own.length)} flush>
                            {lists.own.map((row) => (
                                <PipelineRow key={row.id} row={row} dense={false} />
                            ))}
                        </Section>
                    )}
                    {lists.examples.length > 0 && (
                        <Section
                            title={LABELS.pipelines.lists.examples}
                            meta={String(lists.examples.length)}
                            flush
                            actions={
                                lists.examples.length > EXAMPLES_SHOWN && (
                                    <TextLink
                                        variant="aside"
                                        className="text-xs font-normal"
                                        aria-expanded={allExamples}
                                        onPress={toggleExamples}
                                    >
                                        {allExamples
                                            ? LABELS.pipelines.lists.fewer_examples
                                            : LABELS.pipelines.lists.all_examples}
                                    </TextLink>
                                )
                            }
                        >
                            {examples.map((row) => (
                                <PipelineRow key={row.id} row={row} dense />
                            ))}
                        </Section>
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
                <Chip icon={<ICONS.schedule aria-hidden />}>
                    {`${String(row.schedules)} ${counted(row.schedules, LABELS.word.schedule.count)}`}
                </Chip>
            )}
            {sources.map((kind) => (
                <Chip key={kind} icon={<ICONS.source aria-hidden />}>
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
                    {heading.code !== null && <InlineCode value={heading.code} tone="muted" bare size="xs" />}
                    {mark !== null && (
                        <Chip tone="critical" title={mark.title}>
                            {mark.label}
                        </Chip>
                    )}
                    {retired !== null && (
                        <Chip tone="absent" title={LABELS.pipelines.deactivated.explained}>
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
