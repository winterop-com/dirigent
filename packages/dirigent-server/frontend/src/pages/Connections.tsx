import { PlugZap, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { ConnectionDialog } from '@/components/connections/ConnectionDialog'
import { HealthSaid } from '@/components/connections/Health'
import { NewConnection } from '@/components/connections/NewConnection'
import { Code } from '@/components/ds/Code'
import { ListTable, type Column } from '@/components/list/ListTable'
import { Mark } from '@/components/Mark'
import { PageHeader } from '@/components/ds/PageHeader'
import { PageState } from '@/components/PageState'
import { Refusable } from '@/components/Refusable'
import { sayRefusal } from '@/components/Refusal'
import { Button } from '@/components/ui/button'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@/hooks/use-store'
import {
    checkConnection,
    connectionPath,
    connectionsNote,
    healthOf,
    NEW_CONNECTION_KEY,
    readConnection,
    readConnectionKinds,
    readConnections,
    withCheck,
    type ConnectionOut,
    type SurfaceEntry,
} from '@/lib/connections'
import { formatInstant, formatRelative } from '@/lib/format'
import { LABELS } from '@/lib/labels'
import { kindGlyph } from '@/lib/glyphs'
import { kindMarks } from '@/lib/marks'
import { headingOf, oneLine } from '@/lib/identity'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { cn } from '@/lib/utils'

const connectionId = (row: ConnectionOut) => row.code

/**
 * Every credential this instance holds, in code order.
 *
 * A SECRET IS NEVER ON THIS SCREEN. The API redacts every secret field before it answers, and
 * no row reads a config value at all: what a row says is a code, a kind, and how the last check
 * went. The settings are the dialog's, where a secret is dots or a write-only box.
 *
 * A ROW IS ONE LINE. The code and its kind, the health dot, and how long ago -- three cells that
 * fit the window rather than a summary line and a description column that push the health off the
 * side of the table.
 *
 * THE CHOSEN ROW IS THE ADDRESS. `/connections/<code>` is this screen with that credential's dialog
 * open over it, so a step's connection is one link away from the step naming it -- and a code past
 * the pages read so far is read on its own rather than made to depend on where its row falls.
 *
 * A CHECK IS A WRITE, AND THE ROW IS WHAT IT ANSWERS. `POST /connections/{code}/$check` opens
 * the credential, asks the external system, and records the three fields the health column
 * draws -- so the row is updated from the report rather than by reading the listing again, and
 * the row somebody just pressed stays where it was.
 *
 * THE SCHEMAS ARE READ WHEN A FORM NEEDS THEM. The kinds and the config schema each one
 * publishes come from `GET /blocks`, which is every installed block as well, so opening a row or
 * the dialog is what asks for it. The mark a row leads with is not this read: `lib/marks` holds
 * what the packs declare for every screen that draws a kind.
 */
export function Connections() {
    const { code: chosen = null } = useParams()
    const navigate = useNavigate()
    const [params, setParams] = useSearchParams()
    // The kind a link asked for a credential of, which is what opens the dialog on that kind.
    const asked = params.get(NEW_CONNECTION_KEY)
    const [creating, setCreating] = useState(false)
    // Open while a link is asking for a kind, and while somebody opened it on this screen.
    const minting = creating || asked !== null
    // What a check or a save has since made of a row, over the page it was read on.
    const [fresher, setFresher] = useState<Record<string, ConnectionOut>>({})
    const [checking, setChecking] = useState<string | null>(null)
    const [kinds, setKinds] = useState<SurfaceEntry[] | null>(null)

    const { state, more, reload } = usePaged(readConnections, connectionId)

    const rows = useMemo(() => state.rows.map((row) => fresher[row.code] ?? row), [fresher, state.rows])
    const listed = rows.find((row) => row.code === chosen) ?? null
    // A code the walk has not reached, read on its own. A 404 answers nothing and the dialog
    // stays shut, which is what an address naming no connection should do.
    const ask = useCallback(
        () => (chosen === null || listed !== null ? Promise.resolve(null) : readConnection(chosen)),
        [chosen, listed],
    )
    const alone = useRead(ask)
    const read = alone.value
    // A row read on its own takes what a check or a save has since made of it, as a listed one does.
    const open = listed ?? (read === null ? null : (fresher[read.code] ?? read))

    const held = useCallback((row: ConnectionOut) => {
        setFresher((current) => ({ ...current, [row.code]: row }))
    }, [])

    const check = useCallback(
        (row: ConnectionOut) => {
            setChecking(row.code)
            void checkConnection(row.code)
                .then(
                    (report) => {
                        held(withCheck(row, report, new Date().toISOString()))
                    },
                    // A check that could not be made is not a check that failed: the row keeps
                    // what the last real one said, and the refusal is said where it happened.
                    sayRefusal,
                )
                .finally(() => {
                    setChecking(null)
                })
        },
        [held],
    )

    // One read, made the first time a form could use it and not before.
    const wanted = chosen !== null || minting
    useEffect(() => {
        if (!wanted || kinds !== null) return
        let live = true
        void readConnectionKinds().then(
            (found) => {
                if (live) setKinds(found)
            },
            () => {
                // Without it the form falls back to the keys the connection carries and the
                // kind box to what somebody types. The server decides either way.
            },
        )
        return () => {
            live = false
        }
    }, [kinds, wanted])

    useEffect(() => {
        const note = connectionsNote(rows)
        if (note === null) {
            clearScreenStatus()
            return
        }
        setScreenStatus({ note, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [rows])

    const write = useMayWrite('admin')
    const mayWrite = write.may

    useEffect(() => {
        return registerActions([
            // A row this account's role would be refused is a row the palette does not offer.
            ...(mayWrite
                ? [
                      {
                          id: 'connections:new',
                          title: LABELS.connections.new,
                          group: LIST_GROUP,
                          screen: true,
                          icon: PlugZap,
                          keywords: ['credential', 'create', 'add'],
                          run: () => {
                              setCreating(true)
                          },
                      },
                  ]
                : []),
            {
                id: 'connections:reload',
                title: LABELS.connections.reload,
                group: LIST_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload'],
                run: reload,
            },
        ])
    }, [mayWrite, reload])

    const toListing = useCallback(() => {
        void navigate('/connections', { replace: true })
    }, [navigate])

    return (
        <>
            <PageHeader
                title={LABELS.screen.connections.name}
                aside={
                    <>
                        <ApiChip tag="connections" />
                        <Refusable why={write.why}>
                            <Button
                                size="sm"
                                aria-label={LABELS.connections.new}
                                disabled={!write.may}
                                title={write.why}
                                onClick={() => {
                                    setCreating(true)
                                }}
                            >
                                <PlugZap aria-hidden />
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
                emptyMessage={LABELS.connections.empty}
            >
                <ListTable
                    columns={COLUMNS}
                    rows={rows}
                    rowKey={connectionId}
                    reading={state.reading}
                    next={state.next}
                    onMore={more}
                    noun={LABELS.word.connection.count}
                    onSelect={(row) => {
                        // The row is not another page of history: it is which one is being read.
                        void navigate(connectionPath(row.code), { replace: true })
                    }}
                    selected={(row) => row.code === chosen}
                />
            </PageState>

            {open !== null && (
                <ConnectionDialog
                    key={open.code}
                    connection={open}
                    schema={kinds?.find((entry) => entry.id === open.kind)?.config_schema ?? null}
                    checking={checking === open.code}
                    onCheck={check}
                    onSaved={held}
                    onDeleted={() => {
                        toListing()
                        reload()
                    }}
                    onClose={toListing}
                />
            )}

            <NewConnection
                key={asked ?? ''}
                open={minting}
                kinds={kinds ?? []}
                startKind={asked ?? ''}
                onOpenChange={(next) => {
                    setCreating(next)
                    // The link's question has been answered either way, so it leaves the address
                    // rather than reopening the dialog on the next read of this screen.
                    if (!next && asked !== null) {
                        params.delete(NEW_CONNECTION_KEY)
                        setParams(params, { replace: true })
                    }
                }}
                onCreated={() => {
                    reload()
                }}
            />
        </>
    )
}

/** The columns, each a plain reading of the row. */
const COLUMNS: Column<ConnectionOut>[] = [
    {
        id: 'connection',
        header: LABELS.word.connection.label,
        kind: 'title',
        cell: (row) => <Named row={row} />,
    },
    {
        id: 'kind',
        header: LABELS.word.kind.label,
        cell: (row) => <Kind row={row} />,
    },
    {
        id: 'health',
        header: LABELS.word.health,
        cell: (row) => <Health row={row} />,
    },
    {
        id: 'checked',
        header: LABELS.word.checked.label,
        className: 'text-xs',
        // Nothing rather than an element that draws nothing: a card leaves out the fact a
        // row has none of, and an empty element is a label with a blank beside it.
        cell: (row) => (row.last_check_at === null ? null : <Checked at={row.last_check_at} />),
    },
]

/**
 * What a credential is called and the code it is reached by, with the first line of what it is
 * for under them.
 */
function Named({ row }: { row: ConnectionOut }) {
    const heading = headingOf(row)
    return (
        <span className="flex min-w-0 flex-col py-0.5">
            <span className="flex min-w-0 items-center gap-3">
                <span
                    className={cn('truncate font-semibold', !heading.named && 'font-mono')}
                    title={heading.title}
                >
                    {heading.title}
                </span>
                {heading.code !== null && <Code value={heading.code} />}
            </span>
            {row.description !== null && (
                <span
                    className="mt-1 truncate text-xs text-muted-foreground"
                    title={oneLine(row.description)}
                >
                    {oneLine(row.description)}
                </span>
            )}
        </span>
    )
}

/** Which kind a credential is: its mark, and the kind in mono with no hue. */
function Kind({ row }: { row: ConnectionOut }) {
    const marks = useStore(kindMarks)
    return (
        <span className="flex min-w-0 items-center gap-2">
            <Mark glyph={kindGlyph(row.kind, marks)} />
            <Code value={row.kind} />
        </span>
    )
}

/** Whether this credential answered the last time anything asked it. */
function Health({ row }: { row: ConnectionOut }) {
    return <HealthSaid view={healthOf(row)} focusable />
}

/** When the last check was made. A row nothing has checked says so in the health cell. */
function Checked({ at }: { at: string }) {
    return (
        <span className="text-muted-foreground" title={formatInstant(at)}>
            {formatRelative(at)}
        </span>
    )
}
