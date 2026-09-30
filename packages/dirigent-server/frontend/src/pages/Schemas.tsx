import { FileJson, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader, PageState } from '@/components/PageState'
import { Refusable } from '@/components/Refusable'
import { NewSchema } from '@/components/schemas/NewSchema'
import { SchemaPanel } from '@/components/schemas/SchemaPanel'
import { Button } from '@/components/ui/button'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { useRead } from '@/hooks/use-read'
import { headingOf, oneLine } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { closePanel, fillPanel, openPanel } from '@/lib/panels'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { readSchema, readSchemas, schemasNote, type SchemaOut } from '@/lib/schemas'
import { cn } from '@/lib/utils'

const schemaId = (row: SchemaOut) => row.code

/**
 * Every JSON Schema this instance holds, in code order.
 *
 * A SCHEMA IS LOCALLY AUTHORED. What is on this screen is a shape somebody wrote to say what a
 * payload should look like, applied like a pipeline or a connection -- never fetched from
 * anywhere. Its code, title and description are the schema's own `$id`, `title` and
 * `description`, so a row reads the same quartet every other screen reads.
 *
 * THE CHOSEN ROW IS THE ADDRESS. `/schemas/<code>` is this screen with that schema in the panel,
 * so a shape somebody is reading is a link they can send -- and a code past the pages read so far
 * is read on its own rather than made to depend on where its row happens to fall.
 *
 * THE BODY IS THE SCHEMA, AND IT IS EDITED WHERE IT IS READ. Opening a row shows the schema
 * itself in the editor it was written in, checked against 2020-12 as it is typed, with the
 * window every pane too small for what it holds offers. A shape somebody got wrong is corrected
 * here; the code is not, because the route addresses the schema by it.
 */
export function Schemas() {
    const { code: chosen = null } = useParams()
    const navigate = useNavigate()
    const [creating, setCreating] = useState(false)
    const { state, more, reload } = usePaged(readSchemas, schemaId)
    // What a save has since made of a row, folded over the listing rather than re-read: a
    // reload blanks the rows while it is in flight, and the panel would empty under the hands
    // that just pressed Save.
    const [fresher, setFresher] = useState<Record<string, SchemaOut>>({})

    const rows = useMemo(() => state.rows.map((row) => fresher[row.code] ?? row), [fresher, state.rows])
    const listed = rows.find((row) => row.code === chosen) ?? null
    // A code the walk has not reached, read on its own. A 404 answers nothing and the panel
    // stays shut, which is what an address naming no schema should do.
    const ask = useCallback(
        () => (chosen === null || listed !== null ? Promise.resolve(null) : readSchema(chosen)),
        [chosen, listed],
    )
    const alone = useRead(ask)
    const read = alone.value
    const open = listed ?? (read === null ? null : (fresher[read.code] ?? read))

    const held = useCallback((row: SchemaOut) => {
        setFresher((current) => ({ ...current, [row.code]: row }))
    }, [])

    // A code that is gone is not a code with a fresher row: one stored under it again is a new
    // schema, and the row this held would shadow it.
    const forget = useCallback((code: string) => {
        setFresher((current) => {
            const { [code]: _gone, ...rest } = current
            return rest
        })
    }, [])

    // The address is the selection, so a link straight to a schema opens the panel it names.
    useEffect(() => {
        if (chosen !== null) openPanel()
    }, [chosen])

    useEffect(() => {
        const note = schemasNote(rows)
        if (note === null) {
            clearScreenStatus()
            return
        }
        setScreenStatus({ note, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [rows])

    useEffect(() => {
        if (open === null) return
        return fillPanel(
            [
                {
                    id: 'schema',
                    label: LABELS.word.schema.label,
                    render: () => (
                        <SchemaPanel
                            key={open.code}
                            schema={open}
                            onSaved={held}
                            onDeleted={() => {
                                forget(open.code)
                                void navigate('/schemas', { replace: true })
                                closePanel()
                                reload()
                            }}
                        />
                    ),
                },
            ],
            { screen: 'schemas' },
        )
    }, [forget, held, navigate, open, reload])

    const write = useMayWrite('admin')
    const mayWrite = write.may

    useEffect(() => {
        return registerActions([
            // A row this account's role would be refused is a row the palette does not offer.
            ...(mayWrite
                ? [
                      {
                          id: 'schemas:new',
                          title: LABELS.schemas.new,
                          group: LIST_GROUP,
                          screen: true,
                          icon: FileJson,
                          keywords: ['json schema', 'create', 'add', 'shape'],
                          run: () => {
                              setCreating(true)
                          },
                      },
                  ]
                : []),
            {
                id: 'schemas:reload',
                title: LABELS.schemas.reload,
                group: LIST_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload'],
                run: reload,
            },
        ])
    }, [mayWrite, reload])

    const columns = useMemo(() => buildColumns(), [])

    return (
        <>
            <PageHeader
                title={LABELS.screen.schemas.name}
                aside={
                    <>
                        <ApiChip tag="schemas" />
                        <Refusable why={write.why}>
                            <Button
                                size="sm"
                                aria-label={LABELS.schemas.new}
                                disabled={!write.may}
                                title={write.why}
                                onClick={() => {
                                    setCreating(true)
                                }}
                            >
                                <FileJson aria-hidden />
                                {LABELS.action.new}
                            </Button>
                        </Refusable>
                    </>
                }
            />
            <PageState
                loading={!state.read}
                problem={state.problem}
                empty={rows.length === 0}
                emptyMessage={LABELS.schemas.empty}
            >
                <ListTable
                    columns={columns}
                    rows={rows}
                    rowKey={schemaId}
                    reading={state.reading}
                    next={state.next}
                    onMore={more}
                    noun={LABELS.word.schema.count}
                    onSelect={(row) => {
                        // The row is not another page of history: it is which one is being read.
                        void navigate(`/schemas/${encodeURIComponent(row.code)}`, { replace: true })
                    }}
                    selected={(row) => row.code === chosen}
                    onClose={() => {
                        void navigate('/schemas', { replace: true })
                        closePanel()
                    }}
                />
            </PageState>
            <NewSchema open={creating} onOpenChange={setCreating} onCreated={reload} />
        </>
    )
}

function buildColumns(): Column<SchemaOut>[] {
    return [
        { id: 'schema', header: LABELS.word.schema.label, kind: 'title', cell: (row) => <Named row={row} /> },
        {
            id: 'description',
            header: LABELS.word.description,
            kind: 'prose',
            // The one line a row has room for, and nothing where the schema says nothing.
            cell: (row) => {
                const text = row.description === null ? '' : oneLine(row.description)
                if (text === '') return null
                return (
                    <p className="truncate text-xs text-muted-foreground" title={text}>
                        {text}
                    </p>
                )
            },
        },
    ]
}

/** What a schema is called and the code it is reached by. */
function Named({ row }: { row: SchemaOut }) {
    const heading = headingOf(row)
    return (
        <span className="flex min-w-0 items-center gap-2">
            <span
                className={cn('truncate', heading.named ? 'font-semibold' : 'font-mono font-semibold')}
                title={heading.title}
            >
                {heading.title}
            </span>
            {heading.code !== null && (
                <span className="shrink-0 font-mono text-xs text-muted-foreground" title={heading.code}>
                    {heading.code}
                </span>
            )}
        </span>
    )
}
