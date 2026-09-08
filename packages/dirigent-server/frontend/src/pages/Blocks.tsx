import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiChip } from '@/components/ApiChip'
import { KindChip } from '@/components/KindChip'
import { MarkdownLine } from '@/components/Markdown'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader, PageState } from '@/components/PageState'
import { Fact, Section } from '@/components/run/Panel'
import { Input } from '@/components/ui/input'
import { useRead } from '@/hooks/use-read'
import {
    byGroup,
    defaultLabel,
    factsOf,
    narrowBlocks,
    narrowEntries,
    readCatalog,
    typeLabel,
    type BlockEntry,
    type CatalogEntry,
} from '@/lib/blocks'
import { fillPanel, openPanel } from '@/lib/panels'
import { fieldsOf, type FieldDescriptor } from '@/lib/schema-form'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'

const blockId = (entry: BlockEntry) => entry.id

/** One supporting registry, shelved under its own heading. */
interface Registry {
    key: 'scheme' | 'notifier' | 'connection'
    title: string
    noun: string
}

const REGISTRIES: Registry[] = [
    { key: 'scheme', title: 'Storage schemes', noun: 'schemes' },
    { key: 'notifier', title: 'Notifiers', noun: 'notifiers' },
    { key: 'connection', title: 'Connection kinds', noun: 'connection kinds' },
]

const entryKeyOf = (registry: Registry['key']) => (entry: CatalogEntry) => `${registry}:${entry.id}`

/** The catalog arrives whole, so the table's cursor walk has nothing to walk. */
const NO_MORE = () => {
    // One answer carried every block. There is no next page to ask for.
}

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

    const blocks = useMemo(() => value?.blocks ?? [], [value])
    const shown = useMemo(() => narrowBlocks(blocks, needle), [blocks, needle])
    const groups = useMemo(() => byGroup(shown), [shown])
    const schemes = useMemo(() => narrowEntries(value?.storage_schemes ?? [], needle), [value, needle])
    const notifiers = useMemo(() => narrowEntries(value?.notifiers ?? [], needle), [value, needle])
    const connectionKinds = useMemo(
        () => narrowEntries(value?.connection_kinds ?? [], needle),
        [value, needle],
    )
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
    }, [blocks, read, value])

    useEffect(() => {
        if (open !== null) {
            return fillPanel([
                { id: 'block', label: 'Block', render: () => <BlockPanel entry={open} /> },
            ], { screen: 'blocks' })
        }
        if (openEntry !== null) {
            const { registry, entry } = openEntry
            return fillPanel([
                { id: 'entry', label: registry.title, render: () => <EntryPanel entry={entry} /> },
            ], { screen: 'blocks' })
        }
        return
    }, [open, openEntry])

    const select = useCallback((entry: BlockEntry) => {
        setChosen(`block:${entry.id}`)
        openPanel()
    }, [])

    return (
        <>
            <PageHeader
                title="Blocks"
                aside={<ApiChip tag="blocks" />}
            />

            <div className="mb-4 flex flex-wrap items-center gap-2">
                <Input
                    className="w-56"
                    value={needle}
                    onChange={(event) => {
                        setNeedle(event.target.value)
                    }}
                    placeholder="Search blocks"
                    aria-label="Search blocks by id or summary"
                />
            </div>

            <PageState
                loading={!read}
                problem={problem}
                empty={shown.length === 0 && schemes.length === 0 && notifiers.length === 0 && connectionKinds.length === 0}
                emptyMessage={
                    blocks.length === 0
                        ? 'No blocks installed — plugins contribute them.'
                        : 'Nothing in the catalog matches that.'
                }
            >
                <div className="flex flex-col gap-6">
                    {groups.map(([group, members]) => (
                        <section key={group}>
                            <h2 className="text-faint mb-1.5 font-mono text-xs font-semibold tracking-wide uppercase">
                                {group}
                            </h2>
                            <ListTable
                                chrome={{ footer: false }}
                                fixed
                                columns={COLUMNS}
                                rows={members}
                                rowKey={blockId}
                                reading={false}
                                next={null}
                                onMore={NO_MORE}
                                noun="blocks"
                                onSelect={select}
                                selected={(entry) => `block:${entry.id}` === chosen}
                            />
                        </section>
                    ))}

                    {REGISTRIES.map((registry) => {
                        const rows = registryRows[registry.key]
                        if (rows.length === 0) return null
                        return (
                            <section key={registry.key}>
                                <h2 className="text-faint mb-1.5 font-mono text-xs font-semibold tracking-wide uppercase">
                                    {registry.title}
                                </h2>
                                <ListTable
                                    chrome={{ footer: false }}
                                    fixed
                                    columns={entryColumns(registry.key)}
                                    rows={rows}
                                    rowKey={entryKeyOf(registry.key)}
                                    reading={false}
                                    next={null}
                                    onMore={NO_MORE}
                                    noun={registry.noun}
                                    onSelect={(entry) => {
                                        setChosen(entryKeyOf(registry.key)(entry))
                                        openPanel()
                                    }}
                                    selected={(entry) => entryKeyOf(registry.key)(entry) === chosen}
                                />
                            </section>
                        )
                    })}
                </div>
            </PageState>
        </>
    )
}

const COLUMNS: Column<BlockEntry>[] = [
    {
        id: 'block',
        header: 'Block',
        // The lead cell takes the width the other columns do not, and its own text truncates
        // inside it rather than pushing the table wider than the screen.
        className: 'w-full max-w-0',
        cell: (entry) => (
            <div className="min-w-0">
                {/* A block has no name, so the title is the id and wears the mono face itself. */}
                <span className="font-mono text-sm font-semibold">{entry.id}</span>
                <p className="text-muted-foreground truncate text-xs" title={entry.summary}>
                    {entry.summary}
                </p>
            </div>
        ),
    },
    {
        id: 'kind',
        header: 'Kind',
        className: 'w-32 whitespace-nowrap',
        cell: (entry) => <KindChip kind={entry.kind} />,
    },
    {
        id: 'plugin',
        header: 'Plugin',
        className: 'w-36 font-mono text-xs whitespace-nowrap',
        cell: (entry) => <span className="text-muted-foreground">{entry.plugin}</span>,
    },
]

/** A supporting registry's row: the id, and the line its own schema opens with. */
/**
 * A registry row wears its kind the way a block row does: the section heading says it too,
 * but a row read alone -- searched, remembered, screenshotted -- has to say what it is.
 */
function entryColumns(kind: Registry['key']): Column<CatalogEntry>[] {
    // The chip says what the thing contributed, in the reader's word: an s3 entry under
    // storage schemes is storage; "scheme" is the URI mechanics, not the kind.
    const worn = kind === 'scheme' ? 'storage' : kind
    return [
    {
        id: 'entry',
        header: 'Entry',
        className: 'w-full max-w-0',
        cell: (entry) => {
            const summary = typeof entry.config_schema.description === 'string' ? entry.config_schema.description : ''
            return (
                <div className="min-w-0">
                    <span className="font-mono text-sm font-semibold">{entry.id}</span>
                    <p className="text-muted-foreground truncate text-xs" title={summary}>
                        {summary}
                    </p>
                </div>
            )
        },
    },
    {
        id: 'kind',
        header: 'Kind',
        className: 'w-32 whitespace-nowrap',
        cell: () => <KindChip kind={worn} />,
    },
    {
        id: 'plugin',
        header: 'Plugin',
        className: 'w-36 font-mono text-xs whitespace-nowrap',
        cell: (entry) => <span className="text-muted-foreground">{entry.plugin}</span>,
    },
    ]
}

/** One supporting entry: what it is, and the config its kind takes. */
function EntryPanel({ entry }: { entry: CatalogEntry }) {
    const fields = useMemo(() => fieldsOf(entry.config_schema), [entry])
    const summary = typeof entry.config_schema.description === 'string' ? entry.config_schema.description : null

    return (
        <div className="flex flex-col gap-4 p-4">
            <div className="space-y-1">
                <h2 className="font-mono text-sm font-semibold">{entry.id}</h2>
                {summary !== null && <p className="text-muted-foreground text-sm">{summary}</p>}
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    <Fact term="plugin" detail={entry.plugin} />
                </dl>
            </div>

            <Section title="Config">
                {fields.length === 0 ? (
                    <p className="text-muted-foreground text-sm">This takes no configuration.</p>
                ) : (
                    <div className="flex flex-col gap-4">
                        {fields.map((field) => (
                            <FieldReference key={field.name} field={field} />
                        ))}
                    </div>
                )}
            </Section>
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
                <p>
                    <KindChip kind={entry.kind} />
                </p>
                <p className="text-muted-foreground text-sm">{entry.summary}</p>
            </div>

            <Section title="Facts">
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
                    {facts.map((fact) => (
                        <Fact key={fact.term} term={fact.term} detail={fact.detail} />
                    ))}
                </dl>
            </Section>

            <Section title="Config">
                {fields.length === 0 ? (
                    <p className="text-muted-foreground text-sm">This block takes no configuration.</p>
                ) : (
                    <div className="flex flex-col gap-4">
                        {fields.map((field) => (
                            <FieldReference key={field.name} field={field} />
                        ))}
                    </div>
                )}
            </Section>
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
                <span className="text-muted-foreground text-xs">{typeLabel(field)}</span>
                {field.required && <span className="text-primary text-xs">required</span>}
                {field.hint !== null && <span className="text-faint text-xs">{field.hint}</span>}
                {fallback !== null && <span className="text-faint text-xs">default {fallback}</span>}
            </div>
            {field.options.length > 0 && (
                <p className="text-muted-foreground font-mono text-xs">{field.options.map((option) => option.label).join(' · ')}</p>
            )}
            {field.help !== null && (
                <p className="text-muted-foreground text-xs">
                    <MarkdownLine text={field.help} />
                </p>
            )}
        </div>
    )
}
