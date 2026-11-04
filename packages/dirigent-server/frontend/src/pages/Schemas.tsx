import { FileJson, RefreshCw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader } from '@/components/ds/PageHeader'
import { PageState } from '@/components/PageState'
import { NewSchema } from '@/components/schemas/NewSchema'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { headingOf, oneLine } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
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
                aside={<ApiChip tag="schemas" />}
                actions={[
                    {
                        id: 'new',
                        label: LABELS.action.new,
                        ariaLabel: LABELS.schemas.new,
                        variant: 'default',
                        disabled: !write.may,
                        why: write.why ?? undefined,
                        onClick: () => {
                            setCreating(true)
                        },
                    },
                ]}
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
