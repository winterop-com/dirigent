import { FileJson, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { ApiChip } from '@/components/ApiChip'
import { Description } from '@/components/Description'
import { JsonBlock } from '@/components/JsonBlock'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader, PageState } from '@/components/PageState'
import { Refusable } from '@/components/Refusable'
import { sayRefusal } from '@/components/Refusal'
import { NewSchema } from '@/components/schemas/NewSchema'
import { Button } from '@/components/ui/button'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { headingOf, oneLine } from '@/lib/identity'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { fillPanel, openPanel } from '@/lib/panels'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { deleteSchema, readSchemas, schemasNote, type SchemaOut } from '@/lib/schemas'

const schemaId = (row: SchemaOut) => row.code

/**
 * Every JSON Schema this instance holds, in code order.
 *
 * A SCHEMA IS LOCALLY AUTHORED. What is on this screen is a shape somebody wrote to say what a
 * payload should look like, applied like a pipeline or a connection -- never fetched from
 * anywhere. Its code, title and description are the schema's own `$id`, `title` and
 * `description`, so a row reads the same quartet every other screen reads.
 *
 * THE BODY IS THE SCHEMA. Opening a row shows the schema itself, coloured, with the window the
 * step panel uses -- a schema is JSON, and the reader wants to read it.
 */
export function Schemas() {
    const [chosen, setChosen] = useState<string | null>(null)
    const [creating, setCreating] = useState(false)
    const { state, more, reload } = usePaged(readSchemas, schemaId)

    const rows = state.rows
    const open = rows.find((row) => row.code === chosen) ?? null

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
                    label: 'Schema',
                    render: () => <SchemaPanel key={open.code} schema={open} onDeleted={reload} />,
                },
            ],
            { screen: 'schemas' },
        )
    }, [open, reload])

    const write = useMayWrite('admin')
    const mayWrite = write.may

    useEffect(() => {
        return registerActions([
            // A row this account's role would be refused is a row the palette does not offer.
            ...(mayWrite
                ? [
                      {
                          id: 'schemas:new',
                          title: 'New schema',
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
                title: 'Read the schemas listing again',
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
                title="Schemas"
                aside={
                    <>
                        <ApiChip tag="schemas" />
                        <Refusable why={write.why}>
                            <Button
                                size="sm"
                                aria-label="New schema"
                                disabled={!write.may}
                                title={write.why}
                                onClick={() => {
                                    setCreating(true)
                                }}
                            >
                                <FileJson aria-hidden />
                                New
                            </Button>
                        </Refusable>
                    </>
                }
            />
            <PageState
                loading={!state.read}
                problem={state.problem}
                empty={rows.length === 0}
                emptyMessage="No schemas."
            >
                <ListTable
                    columns={columns}
                    rows={rows}
                    rowKey={schemaId}
                    reading={state.reading}
                    next={state.next}
                    onMore={more}
                    noun="schemas"
                    onSelect={(row) => {
                        setChosen(row.code)
                        openPanel()
                    }}
                    selected={(row) => row.code === chosen}
                />
            </PageState>
            <NewSchema open={creating} onOpenChange={setCreating} onCreated={reload} />
        </>
    )
}

function buildColumns(): Column<SchemaOut>[] {
    return [
        { id: 'schema', header: 'Schema', cell: (row) => <Named row={row} /> },
        { id: 'description', header: 'Description', cell: (row) => <Said description={row.description} /> },
    ]
}

/** What a schema is called and the code it is reached by. */
function Named({ row }: { row: SchemaOut }) {
    const heading = headingOf(row)
    return (
        <span className="flex items-center gap-2">
            <span className={heading.named ? 'font-semibold' : 'font-mono font-semibold'}>{heading.title}</span>
            {heading.code !== null && <span className="text-muted-foreground font-mono text-xs">{heading.code}</span>}
        </span>
    )
}

/** The one line a row has space for, or nothing when the schema says nothing. */
function Said({ description }: { description: string | null }) {
    const text = description === null ? '' : oneLine(description)
    if (text === '') return null
    return (
        <p className="text-muted-foreground max-w-64 truncate text-xs" title={text}>
            {text}
        </p>
    )
}

/** The selected schema, in the right panel: its description, and the schema body itself. */
function SchemaPanel({ schema, onDeleted }: { schema: SchemaOut; onDeleted: () => void }) {
    const [removing, setRemoving] = useState(false)
    const write = useMayWrite('admin')
    const remove = () => {
        setRemoving(true)
        void deleteSchema(schema.code)
            .then(onDeleted, sayRefusal)
            .finally(() => {
                setRemoving(false)
            })
    }
    return (
        <div className="flex min-h-0 flex-col gap-4 p-4">
            <Description text={schema.description} />
            <JsonBlock title={`${schema.code} · schema`} text={JSON.stringify(schema.body, null, 2)} className="max-h-[60vh]" />
            <Refusable why={write.why}>
                <Button
                    variant="outline"
                    size="sm"
                    className="self-start"
                    disabled={removing || !write.may}
                    title={write.why}
                    onClick={remove}
                >
                    {removing ? 'Deleting' : 'Delete'}
                </Button>
            </Refusable>
        </div>
    )
}
