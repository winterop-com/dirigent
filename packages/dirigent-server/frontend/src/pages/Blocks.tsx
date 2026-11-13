import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { KindChip } from '@/components/KindChip'
import { Description } from '@/components/Description'
import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { DataTable, DataTableGroup, TableCellFill, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { ListingBar } from '@winterop-com/sokkel-ui/ListingBar'
import { PageHeader } from '@/components/ds/PageHeader'
import { Section } from '@winterop-com/sokkel-ui/Section'
import { PageState } from '@/components/PageState'
import { DescriptionList } from '@winterop-com/sokkel-ui/DescriptionList'
import { PanelGroup } from '@/components/run/Panel'
import { SearchField } from '@winterop-com/sokkel-ui/SearchField'
import { useRead } from '@/hooks/use-read'
import { useRowPress } from '@/hooks/use-row-press'
import {
    byGroup,
    defaultLabel,
    factsOf,
    narrowBlocks,
    narrowEntries,
    readCatalog,
    typeLabel,
    unsafeChip,
    type BlockEntry,
    type CatalogEntry,
} from '@/lib/blocks'
import { examplesPerBlock, readAllExamples } from '@/lib/examples'
import { SEARCH_PLACEHOLDER, SEARCH_WORDS, SECTION_LISTING } from '@/lib/design-system'
import { counted as pick, type Counted, LABELS } from '@/lib/labels'
import { closePanel, fillPanel, openPanel } from '@/lib/panels'
import { rowsRead } from '@/lib/paging'
import { fieldsOf, type FieldDescriptor } from '@/lib/schema-form'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'

const blockId = (entry: BlockEntry) => entry.id

/** One supporting registry, shelved under its own heading. */
interface Registry {
    key: 'scheme' | 'notifier' | 'connection'
    title: string
    noun: Counted<string>
}

const REGISTRIES: Registry[] = [
    {
        key: 'scheme',
        title: LABELS.blocks.registry.scheme.title,
        noun: LABELS.blocks.registry.scheme.noun,
    },
    {
        key: 'notifier',
        title: LABELS.blocks.registry.notifier.title,
        noun: LABELS.blocks.registry.notifier.noun,
    },
    {
        key: 'connection',
        title: LABELS.blocks.registry.connection.title,
        noun: LABELS.blocks.registry.connection.noun,
    },
]

const entryKeyOf = (registry: Registry['key']) => (entry: CatalogEntry) => `${registry}:${entry.id}`

/**
 * Every block this instance can run, and the config each one takes.
 *
 * THE BROWSABLE HALF OF THE STEP FORM. The pipeline editor already renders one block's schema,
 * for the step in front of somebody; this is the same data with nothing chosen yet -- so
 * `lib/schema-form` reads the schema here too, and a field that is a select there is an enum
 * here rather than two modules disagreeing about what a block takes.
 *
 * ONE ANSWER, NARROWED IN THE BROWSER. `GET /blocks` is the whole catalog rather than a page of
 * it, so the box narrows all of it and the empty state can say the search found nothing. This
 * is the one listing in the app where a client-side filter is not a squint at a partial read.
 *
 * THE REFERENCE IS READ-ONLY AND SAYS SO BY HAVING NO CONTROLS. A catalog entry is what a block
 * takes, not a value anybody is setting; a form here would offer to edit a document that does
 * not exist. What it states per field is the key, the shape, the default and the block author's
 * own line about it.
 */
export function Blocks() {
    const [needle, setNeedle] = useState('')
    const [chosen, setChosen] = useState<string | null>(null)

    const { value, problem, read } = useRead(readCatalog)
    // The corpus is a cached read shared with the Examples screen, so this costs one request
    // per tab however often either screen is opened.
    const corpus = useRead(readAllExamples)
    const uses = useMemo(() => examplesPerBlock(corpus.value ?? []), [corpus.value])

    const blocks = useMemo(() => value?.blocks ?? [], [value])
    const shown = useMemo(() => narrowBlocks(blocks, needle), [blocks, needle])
    const groups = useMemo(() => byGroup(shown), [shown])
    const schemes = useMemo(() => narrowEntries(value?.storage_schemes ?? [], needle), [value, needle])
    const notifiers = useMemo(() => narrowEntries(value?.notifiers ?? [], needle), [value, needle])
    const connectionKinds = useMemo(
        () => narrowEntries(value?.connection_kinds ?? [], needle),
        [value, needle],
    )
    const columns = useMemo(() => blockColumns(uses), [uses])
    const open = blocks.find((entry) => `block:${entry.id}` === chosen) ?? null
    const registryRows: Record<Registry['key'], CatalogEntry[]> = {
        scheme: schemes,
        notifier: notifiers,
        connection: connectionKinds,
    }
    const openEntry =
        REGISTRIES.flatMap((registry) =>
            registryRows[registry.key].map((entry) => ({ registry, entry })),
        ).find(({ registry, entry }) => entryKeyOf(registry.key)(entry) === chosen) ?? null

    useEffect(() => {
        if (!read) return
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [read])

    useEffect(() => {
        if (open !== null) {
            return fillPanel(
                [{ id: 'block', label: LABELS.word.block.label, render: () => <BlockPanel entry={open} /> }],
                { screen: 'blocks' },
            )
        }
        if (openEntry !== null) {
            const { registry, entry } = openEntry
            return fillPanel(
                [{ id: 'entry', label: registry.title, render: () => <EntryPanel entry={entry} /> }],
                { screen: 'blocks' },
            )
        }
        return
    }, [open, openEntry])

    /** A row by the key it is chosen by, for the catalog and the registries alike. */
    const press = useRowPress<string>(
        (key) => {
            setChosen(key)
            openPanel()
        },
        (key) => key === chosen,
        () => {
            setChosen(null)
            closePanel()
        },
    )

    return (
        <>
            <PageHeader title={LABELS.screen.blocks.name} lead={<ApiChip tag="blocks" />} />

            <ListingBar
                className="mb-4 px-0"
                search={
                    <SearchField
                        placeholder={SEARCH_PLACEHOLDER}
                        words={SEARCH_WORDS}
                        value={needle}
                        label={LABELS.blocks.search}
                        onChange={setNeedle}
                    />
                }
            />

            <PageState
                loading={!read}
                problem={problem}
                empty={
                    shown.length === 0 &&
                    schemes.length === 0 &&
                    notifiers.length === 0 &&
                    connectionKinds.length === 0
                }
                emptyMessage={blocks.length === 0 ? LABELS.blocks.empty : LABELS.blocks.empty_filtered}
            >
                <div className="flex flex-col gap-6">
                    <DataTableGroup>
                        {groups.map(([group, members]) => (
                            <Section
                                key={group}
                                title={<InlineCode value={group} tone="neutral" bare size="xs" />}
                                meta={rowsRead(members.length, LABELS.word.block.count, false)}
                                flush
                            >
                                <DataTable
                                    {...SECTION_LISTING}
                                    bar={false}
                                    rowHeight="auto"
                                    columns={columns}
                                    rows={members}
                                    rowKey={blockId}
                                    onOpen={(entry) => {
                                        press(`block:${entry.id}`)
                                    }}
                                    opened={(entry) => `block:${entry.id}` === chosen}
                                />
                            </Section>
                        ))}
                    </DataTableGroup>

                    <DataTableGroup>
                        {REGISTRIES.map((registry) => {
                            const rows = registryRows[registry.key]
                            if (rows.length === 0) return null
                            return (
                                <Section
                                    key={registry.key}
                                    title={registry.title}
                                    meta={rowsRead(rows.length, registry.noun, false)}
                                    flush
                                >
                                    <DataTable
                                        {...SECTION_LISTING}
                                        bar={false}
                                        rowHeight="auto"
                                        columns={entryColumns(registry.key)}
                                        rows={rows}
                                        rowKey={entryKeyOf(registry.key)}
                                        onOpen={(entry) => {
                                            press(entryKeyOf(registry.key)(entry))
                                        }}
                                        opened={(entry) => entryKeyOf(registry.key)(entry) === chosen}
                                    />
                                </Section>
                            )
                        })}
                    </DataTableGroup>
                </div>
            </PageState>
        </>
    )
}

/** The narrowest an id column is drawn, so the summary cut under a short id still says something. */
const SUMMARY_FLOOR = '16rem'

/**
 * The columns, which differ only by how many shipped documents require each block.
 *
 * A BLOCK IS A REFERENCE UNTIL SOMETHING USES IT. What the catalog says a block takes is only
 * half of what somebody browsing one wants; the other half is a document that actually uses it,
 * and the corpus has one. The count is a link to the Examples screen narrowed to this block,
 * and it is read off the same `requires.blocks` that listing narrows by -- so what the number
 * says is what pressing it shows.
 */
function blockColumns(uses: ReadonlyMap<string, number>): DataColumn<BlockEntry>[] {
    return [
        {
            id: 'block',
            header: LABELS.word.block.label,
            width: 'content',
            minWidth: SUMMARY_FLOOR,
            cell: (entry) => (
                <div className="min-w-0">
                    <div className="flex min-w-0 items-center gap-2">
                        {/* A block has no name, so the title is the id and wears the mono face itself. */}
                        <span className="font-mono text-sm font-semibold">{entry.id}</span>
                        <UnsafeChip entry={entry} />
                    </div>
                    <p className="text-xs text-muted-foreground" title={entry.summary}>
                        <TableCellFill>{entry.summary}</TableCellFill>
                    </p>
                </div>
            ),
        },
        {
            id: 'kind',
            header: LABELS.word.kind.label,
            width: 'minmax(8rem,1fr)',
            cell: (entry) => <KindChip kind={entry.kind} />,
        },
        {
            id: 'examples',
            header: LABELS.word.example.heading,
            width: 'minmax(7rem,1fr)',
            cell: (entry) => <ExampleCount id={entry.id} many={uses.get(entry.id) ?? 0} />,
        },
        {
            id: 'plugin',
            header: LABELS.word.plugin.label,
            width: 'minmax(9rem,1fr)',
            cell: (entry) => (
                <span className="font-mono text-xs whitespace-nowrap text-muted-foreground">
                    {entry.plugin}
                </span>
            ),
        },
    ]
}

/** An unsafe block's chip, saying in its tone and its title whether this instance enables it. */
function UnsafeChip({ entry }: { entry: BlockEntry }) {
    const chip = unsafeChip(entry)
    if (chip === null) return null
    return (
        <Chip tone={chip.tone} title={chip.title}>
            {chip.label}
        </Chip>
    )
}

/** How many shipped documents require one block, as the link that shows them. */
function ExampleCount({ id, many }: { id: string; many: number }) {
    if (many === 0) return <span className="text-xs text-faint">{LABELS.word.none}</span>
    const said = pick(many, LABELS.blocks.example_count)(String(many))
    return (
        <Link
            className="text-xs text-foreground underline-offset-2 hover:underline"
            to={`/examples?block=${encodeURIComponent(id)}`}
            title={LABELS.blocks.example_link(id)}
            onClick={(event) => {
                event.stopPropagation()
            }}
        >
            {said}
        </Link>
    )
}

/** A supporting registry's row: the id, and the line its own schema opens with. */
/**
 * A registry row wears its kind the way a block row does: the section heading says it too,
 * but a row read alone -- searched, remembered, screenshotted -- has to say what it is.
 */
function entryColumns(kind: Registry['key']): DataColumn<CatalogEntry>[] {
    // The chip says what the thing contributed, in the reader's word: an s3 entry under
    // storage schemes is storage; "scheme" is the URI mechanics, not the kind.
    const worn = kind === 'scheme' ? 'storage' : kind
    return [
        {
            id: 'entry',
            header: LABELS.blocks.entry_header,
            width: 'content',
            minWidth: SUMMARY_FLOOR,
            cell: (entry) => {
                const summary =
                    typeof entry.config_schema.description === 'string' ? entry.config_schema.description : ''
                return (
                    <div className="min-w-0">
                        <span className="font-mono text-sm font-semibold">{entry.id}</span>
                        <p className="text-xs text-muted-foreground" title={summary}>
                            <TableCellFill>{summary}</TableCellFill>
                        </p>
                    </div>
                )
            },
        },
        {
            id: 'kind',
            header: LABELS.word.kind.label,
            width: 'minmax(8rem,1fr)',
            cell: () => <KindChip kind={worn} />,
        },
        {
            id: 'plugin',
            header: LABELS.word.plugin.label,
            width: 'minmax(9rem,1fr)',
            cell: (entry) => (
                <span className="font-mono text-xs whitespace-nowrap text-muted-foreground">
                    {entry.plugin}
                </span>
            ),
        },
    ]
}

/** One supporting entry: what it is, and the config its kind takes. */
function EntryPanel({ entry }: { entry: CatalogEntry }) {
    const fields = useMemo(() => fieldsOf(entry.config_schema), [entry])
    const summary =
        typeof entry.config_schema.description === 'string' ? entry.config_schema.description : null

    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="space-y-1">
                <h2 className="font-mono text-sm font-semibold">{entry.id}</h2>
                {summary !== null && <p className="text-sm text-muted-foreground">{summary}</p>}
                <DescriptionList
                    items={[{ term: LABELS.blocks.fact.term.plugin, value: entry.plugin, code: true }]}
                />
            </div>

            <PanelGroup title={LABELS.word.config}>
                {fields.length === 0 ? (
                    <p className="text-sm text-muted-foreground">{LABELS.form.no_configuration}</p>
                ) : (
                    <div className="flex flex-col gap-4">
                        {fields.map((field) => (
                            <FieldReference key={field.name} field={field} />
                        ))}
                    </div>
                )}
            </PanelGroup>
        </div>
    )
}

/**
 * One block, as much of it as the catalog answers with.
 *
 * The facts come before the config because they decide whether a step naming this block will
 * run at all -- `local_execution` is the allowlist gate -- and the config reference is the long
 * half somebody scrolls.
 */
function BlockPanel({ entry }: { entry: BlockEntry }) {
    const fields = useMemo(() => fieldsOf(entry.config_schema), [entry])
    const facts = factsOf(entry)

    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="space-y-1">
                <h2 className="font-mono text-sm font-semibold">{entry.id}</h2>
                <p className="flex items-center gap-2">
                    <KindChip kind={entry.kind} />
                    <UnsafeChip entry={entry} />
                </p>
                <p className="text-sm text-muted-foreground">{entry.summary}</p>
            </div>

            <PanelGroup title={LABELS.blocks.facts_section}>
                <DescriptionList
                    termWidth="10rem"
                    items={facts.map((fact) => ({
                        term: fact.term,
                        value: fact.detail,
                        code: fact.term === LABELS.blocks.fact.term.plugin,
                    }))}
                />
            </PanelGroup>

            <PanelGroup title={LABELS.word.config}>
                {fields.length === 0 ? (
                    <p className="text-sm text-muted-foreground">{LABELS.form.no_configuration}</p>
                ) : (
                    <div className="flex flex-col gap-4">
                        {fields.map((field) => (
                            <FieldReference key={field.name} field={field} />
                        ))}
                    </div>
                )}
            </PanelGroup>
        </div>
    )
}

/**
 * One config key, stated rather than offered.
 *
 * THE SAME ROW THE STEP FORM DRAWS, WITHOUT THE CONTROL: the key in mono as the heading, what
 * is worth knowing beside it, and the block author's own sentence under. A reader moving
 * between this screen and a step's panel is reading one layout twice.
 */
function FieldReference({ field }: { field: FieldDescriptor }) {
    const fallback = defaultLabel(field)
    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-baseline gap-x-2">
                <span className="font-mono text-sm font-medium">{field.name}</span>
                <span className="text-xs text-muted-foreground">{typeLabel(field)}</span>
                {field.required && (
                    <span className="text-xs text-foreground underline-offset-2">
                        {LABELS.blocks.field_required}
                    </span>
                )}
                {field.hint !== null && <span className="text-xs text-faint">{field.hint}</span>}
                {fallback !== null && (
                    <span className="text-xs text-faint">
                        {LABELS.blocks.field_default} {fallback}
                    </span>
                )}
            </div>
            {field.options.length > 0 && (
                <p className="font-mono text-xs text-muted-foreground">
                    {field.options.map((option) => option.label).join(' · ')}
                </p>
            )}
            <Description text={field.help} size="help" />
        </div>
    )
}
