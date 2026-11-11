import { FileJson, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { PageHeader } from '@/components/ds/PageHeader'
import { DataTable, useTableCell, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { ItemHeading } from '@winterop-com/sokkel-ui/ItemHeading'
import { LISTING, shutWith } from '@/lib/design-system'
import { PageState } from '@/components/PageState'
import { NewSchema } from '@/components/schemas/NewSchema'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { headingOf, itemOf, oneLine } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { rowsRead } from '@/lib/paging'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { readSchemas, type SchemaOut } from '@/lib/schemas'
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
 * A ROW OPENS THE SCHEMA'S OWN PAGE, `/schemas/<code>`, where it is edited beside a value it is
 * tried against; a schema just created lands there too.
 */
export function Schemas() {
    const navigate = useNavigate()
    const [creating, setCreating] = useState(false)
    const { state, more, reload } = usePaged(readSchemas, schemaId)
    const rows = state.rows

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

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
                lead={<ApiChip tag="schemas" />}
                primary={{
                    id: 'new',
                    label: LABELS.schemas.new,
                    face: LABELS.action.new,
                    ...shutWith(!write.may, write.why),
                    onSelect: () => {
                        setCreating(true)
                    },
                }}
            />
            <PageState
                loading={!state.read}
                problem={state.problem}
                empty={rows.length === 0}
                emptyMessage={LABELS.schemas.empty}
            >
                <DataTable
                    {...LISTING}
                    columns={columns}
                    rows={rows}
                    rowKey={schemaId}
                    hasMore={state.next !== null}
                    loading={state.reading}
                    onLoadMore={more}
                    foot={rowsRead(rows.length, LABELS.word.schema.count, state.next !== null)}
                    onOpen={(row) => {
                        void navigate(`/schemas/${encodeURIComponent(row.code)}`)
                    }}
                />
            </PageState>
            <NewSchema
                open={creating}
                onOpenChange={setCreating}
                onCreated={(row) => {
                    void navigate(`/schemas/${encodeURIComponent(row.code)}`)
                }}
            />
        </>
    )
}

function buildColumns(): DataColumn<SchemaOut>[] {
    return [
        {
            id: 'schema',
            header: LABELS.word.schema.label,
            width: 'minmax(24rem,2fr)',
            stackTitle: 'free',
            cell: (row) => <Named row={row} />,
        },
        {
            id: 'description',
            header: LABELS.word.description,
            width: 'minmax(10rem,2fr)',
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

/** What a schema is called and the code it is reached by, beside the name in a row and under it on a card. */
function Named({ row }: { row: SchemaOut }) {
    const { stacked } = useTableCell()
    const heading = headingOf(row)
    if (stacked) return <ItemHeading {...itemOf(row)} as="span" />
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
