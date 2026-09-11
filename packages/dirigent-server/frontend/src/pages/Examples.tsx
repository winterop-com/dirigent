import { FilePlus2, RefreshCw } from 'lucide-react'
import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { ANY, Choice } from '@/components/list/Choice'
import { ListTable, type Column } from '@/components/list/ListTable'
import { TagFilter } from '@/components/list/TagFilter'
import { PageHeader, PageState } from '@/components/PageState'
import { Segmented } from '@/components/Segmented'
import { TagChip } from '@/components/TagChip'
import { TagChips } from '@/components/TagChips'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { useRead } from '@/hooks/use-read'
import {
    anythingFiltered,
    carriesNote,
    filtersFromQuery,
    missingCount,
    narrowExamples,
    pluginsOffered,
    queryOf,
    readAllExamples,
    readHoldings,
    requirementsOf,
    requirementsSummary,
    shelvesOffered,
    tagsOffered,
    type ExampleFilters,
    type ExampleOut,
    type Holdings,
} from '@/lib/examples'
import { headingOf, oneLine } from '@/lib/identity'
import { NEW_PIPELINE_PATH } from '@/lib/nav'
import { fillPanel, openPanelTab } from '@/lib/panels'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { STARTER_TAG, instantiate } from '@/lib/starters'
import { cn } from '@/lib/utils'

/**
 * The pane a chosen row opens, which carries the markdown lexer and the editor's own door.
 *
 * A reader who never opens a row downloads neither.
 */
const ExamplePanel = lazy(() =>
    import('@/components/examples/ExamplePanel').then((module) => ({ default: module.ExamplePanel })),
)

/** Which tab of the right panel a chosen row opens. */
const EXAMPLE_TAB = 'example'

/** The corpus arrives whole, so the table's cursor walk has nothing to walk. */
const NO_MORE = () => {
    // One walk carried every document. There is no next page to ask for.
}

const exampleCode = (row: ExampleOut) => row.code

/** What the two-value filter over the corpus calls its halves. */
const WHICH = [
    { value: 'all' as const, label: 'All' },
    { value: 'starters' as const, label: 'Starters' },
]

/**
 * Every document this build's plugins ship, and which of them may be copied.
 *
 * THE CATALOGUE IS READ WHOLE AND NARROWED HERE. `GET /examples` answers what this build
 * installed rather than rows in a database, so the walk is four requests at most and every
 * control on this screen narrows all of it -- which is why the empty state can say a search
 * found nothing rather than "nothing yet", and why a filter here is not the squint at a partial
 * read the listing rule is about. It is the block catalog's standing, not the pipelines
 * listing's.
 *
 * THE FILTERS LIVE IN THE ADDRESS. A narrowed catalogue is a link somebody sends -- and the
 * Blocks screen sends one, `?block=<id>`, for the documents that require a block. The query is
 * replaced rather than pushed, because a filter being assembled is one destination and not six.
 *
 * A ROW OPENS BESIDE THE TABLE. What a reader wants of an example is its text, comments and
 * all, and what it needs of this instance before a copy of it would apply; both are the panel's.
 */
export function Examples() {
    const navigate = useNavigate()
    const [asked, setAsked] = useSearchParams()
    const [chosen, setChosen] = useState<ExampleOut | null>(null)

    const filters = useMemo(() => filtersFromQuery(asked), [asked])
    const change = useCallback(
        (next: ExampleFilters) => {
            setAsked(queryOf(next), { replace: true })
        },
        [setAsked],
    )

    const corpus = useRead(readAllExamples)
    const instance = useRead(readHoldings)
    const holdings = useMemo<Holdings>(
        () => instance.value ?? { blocks: null, connections: null, schemas: null },
        [instance.value],
    )

    const rows = useMemo(() => corpus.value ?? [], [corpus.value])
    const shown = useMemo(() => narrowExamples(rows, filters), [filters, rows])
    const shelves = useMemo(() => shelvesOffered(rows), [rows])
    const plugins = useMemo(() => pluginsOffered(rows), [rows])
    const offered = useMemo(() => tagsOffered(rows), [rows])

    const addTag = useCallback(
        (tag: string) => {
            if (!filters.tags.includes(tag)) change({ ...filters, tags: [...filters.tags, tag] })
        },
        [change, filters],
    )

    const columns = useMemo(() => exampleColumns(holdings, plugins, addTag), [addTag, holdings, plugins])

    const use = useCallback(
        (source: string, code: string) => {
            void navigate(NEW_PIPELINE_PATH, { state: { document: instantiate(source, code) } })
        },
        [navigate],
    )

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [rows.length])

    useEffect(() => {
        return registerActions([
            {
                id: 'examples:starters',
                title: 'Show only the starters',
                group: LIST_GROUP,
                screen: true,
                icon: FilePlus2,
                keywords: ['starter', 'copy', 'new'],
                run: () => {
                    change({ ...filters, starters: true })
                },
            },
            {
                id: 'examples:clear',
                title: 'Clear the filters on the examples listing',
                group: LIST_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['reset', 'all'],
                run: () => {
                    change({ needle: '', tags: [], shelf: '', plugin: '', starters: false, block: '' })
                },
            },
        ])
    }, [change, filters])

    useEffect(() => {
        if (chosen === null) return
        return fillPanel(
            [
                {
                    id: EXAMPLE_TAB,
                    label: 'Example',
                    render: () => (
                        <Suspense fallback={<PanelReading />}>
                            <ExamplePanel
                                key={chosen.code}
                                example={chosen}
                                holdings={holdings}
                                onUse={use}
                            />
                        </Suspense>
                    ),
                },
            ],
            { screen: 'examples' },
        )
    }, [chosen, holdings, use])

    return (
        <>
            <PageHeader
                title="Examples"
                aside={
                    <>
                        <ApiChip tag="examples" />
                        {shown.length !== rows.length && (
                            <span className="text-xs text-muted-foreground">
                                {String(shown.length)} of {String(rows.length)}
                            </span>
                        )}
                    </>
                }
            />

            <div className="mb-4 flex flex-wrap items-center gap-2">
                <Input
                    className="w-56"
                    value={filters.needle}
                    onChange={(event) => {
                        change({ ...filters, needle: event.target.value })
                    }}
                    placeholder="Search examples"
                    aria-label="Search examples by code, name, description or tag"
                />
                <Segmented
                    label="Which documents"
                    value={filters.starters ? 'starters' : 'all'}
                    options={WHICH}
                    onChoose={(which) => {
                        change({ ...filters, starters: which === 'starters' })
                    }}
                />
                <TagFilter
                    chosen={filters.tags}
                    offered={offered}
                    onChange={(tags) => {
                        change({ ...filters, tags })
                    }}
                />
                <Choice
                    label="Shelf"
                    value={filters.shelf}
                    anything="Any shelf"
                    options={shelves.map((shelf) => ({ value: shelf, label: shelf }))}
                    onChange={(shelf) => {
                        change({ ...filters, shelf: shelf === ANY ? '' : shelf })
                    }}
                />
                {/* A choice of one is not a choice: the control appears when a pack is installed. */}
                {plugins.length > 1 && (
                    <Choice
                        label="Plugin"
                        value={filters.plugin}
                        anything="Any plugin"
                        options={plugins.map((plugin) => ({ value: plugin, label: plugin }))}
                        onChange={(plugin) => {
                            change({ ...filters, plugin: plugin === ANY ? '' : plugin })
                        }}
                    />
                )}
                {/* The Blocks screen links here narrowed to one block, and the chip that says
                    so is the chip that takes it off again. */}
                {filters.block !== '' && (
                    <TagChip
                        tag={filters.block}
                        label={`Stop narrowing to ${filters.block}`}
                        onSelect={() => {
                            change({ ...filters, block: '' })
                        }}
                    />
                )}
            </div>

            <PageState
                loading={!corpus.read}
                problem={corpus.problem}
                empty={shown.length === 0}
                emptyMessage={
                    rows.length === 0
                        ? 'No examples installed — plugins contribute them.'
                        : anythingFiltered(filters)
                          ? 'Nothing in the corpus matches that.'
                          : 'No examples.'
                }
            >
                <ListTable
                    columns={columns}
                    rows={shown}
                    rowKey={exampleCode}
                    reading={false}
                    next={null}
                    onMore={NO_MORE}
                    noun="examples"
                    onSelect={(row) => {
                        setChosen(row)
                        openPanelTab(EXAMPLE_TAB)
                    }}
                    selected={(row) => row.code === chosen?.code}
                />
            </PageState>
        </>
    )
}

/** What the panel holds while its own chunk is being fetched. */
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
 * The columns of the corpus.
 *
 * THE STARTER MARK IS THE BADGE AND NOT THE CHIP. `starter` is a tag as well as a field, and a
 * row wearing both would say one fact twice -- so the badge stands beside the title, where what
 * it decides is read, and the chip is taken out of the row's tags.
 *
 * THE REQUIREMENTS COLUMN IS CHECKED AGAINST THIS INSTANCE. It says what the document needs and
 * how much of that is not here, in the two inks the connections column already reads in.
 *
 * THERE IS NO SHELF COLUMN. The corpus tags every document with the shelf it sits on, so the
 * chips already carry it and a column would be the same word twice on one row; the filter
 * beside the table and the panel's facts are where the field itself is read.
 */
function exampleColumns(
    holdings: Holdings,
    plugins: readonly string[],
    onTag: (tag: string) => void,
): Column<ExampleOut>[] {
    return [
        {
            id: 'example',
            header: 'Example',
            className: 'w-full max-w-0',
            cell: (row) => {
                const heading = headingOf(row)
                const carries = carriesNote(row)
                return (
                    <div className="min-w-0">
                        <span className="flex items-center gap-2">
                            <span
                                className={cn(
                                    'truncate font-semibold',
                                    'max-lg:overflow-visible max-lg:whitespace-normal',
                                    !heading.named && 'font-mono',
                                )}
                                title={heading.title}
                            >
                                {heading.title}
                            </span>
                            {row.starter && (
                                <Badge variant="outline" className="shrink-0">
                                    Starter
                                </Badge>
                            )}
                            {carries !== null && (
                                <span
                                    className="shrink-0 text-xs text-muted-foreground"
                                    title="An instance refuses a document that carries these, so a copy has to create them instead."
                                >
                                    {carries}
                                </span>
                            )}
                        </span>
                        <p className="flex items-center gap-2 text-xs">
                            {heading.code !== null && (
                                <span className="font-mono text-muted-foreground">{heading.code}</span>
                            )}
                            {row.description !== null && (
                                <span
                                    className="min-w-0 flex-1 truncate text-muted-foreground"
                                    title={oneLine(row.description)}
                                >
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
            cell: (row) => <TagChips tags={row.tags.filter((tag) => tag !== STARTER_TAG)} onSelect={onTag} />,
        },
        {
            id: 'requires',
            header: 'Requires',
            className: 'whitespace-nowrap',
            cell: (row) => <RequiresCell example={row} holdings={holdings} />,
        },
        // A COLUMN OF ONE REPEATED WORD SAYS NOTHING. With only the core corpus installed
        // every row is shipped by the same distribution, and the panel states it anyway.
        ...(plugins.length > 1
            ? [
                  {
                      id: 'plugin',
                      header: 'Plugin',
                      className: 'w-32 font-mono text-xs whitespace-nowrap',
                      cell: (row: ExampleOut) => <span className="text-muted-foreground">{row.plugin}</span>,
                  },
              ]
            : []),
    ]
}

/** What a document needs of this instance, counted, with what is not here said in critical ink. */
function RequiresCell({ example, holdings }: { example: ExampleOut; holdings: Holdings }) {
    const items = requirementsOf(example.requires, holdings)
    const summary = requirementsSummary(items)
    if (summary === null) return null
    const missing = missingCount(items)
    return (
        <span className={cn('text-xs', missing === 0 ? 'text-muted-foreground' : 'text-critical')}>
            {summary}
        </span>
    )
}
