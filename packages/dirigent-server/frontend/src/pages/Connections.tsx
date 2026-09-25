import { PlugZap, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'

import { ApiChip } from '@/components/ApiChip'
import { ConnectionForm } from '@/components/connections/ConnectionForm'
import { HealthSaid } from '@/components/connections/Health'
import { NewConnection } from '@/components/connections/NewConnection'
import { KindChip } from '@/components/KindChip'
import { useListCards } from '@/components/list/ListForm'
import { ListTable, type Column } from '@/components/list/ListTable'
import { Mark } from '@/components/Mark'
import { PageHeader, PageState } from '@/components/PageState'
import { Refusable } from '@/components/Refusable'
import { sayRefusal } from '@/components/Refusal'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
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
import { kindGlyph } from '@/lib/glyphs'
import { kindMarks } from '@/lib/marks'
import { headingOf } from '@/lib/identity'
import { fillPanel, openPanel } from '@/lib/panels'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { cn } from '@/lib/utils'

const connectionId = (row: ConnectionOut) => row.code

/**
 * Every credential this instance holds, in code order.
 *
 * A SECRET IS NEVER ON THIS SCREEN. The API redacts every secret field before it answers, and
 * no row reads a config value at all: what a row says is a code, a kind, and how the last check
 * went. The settings are the form's, where a secret is a write-only box.
 *
 * A ROW IS ONE LINE. The code and its kind, the health dot and its word, how long ago, and the
 * button that asks again -- four cells that fit the window rather than a summary line and a
 * description column that push the health off the side of the table.
 *
 * THE CHOSEN ROW IS THE ADDRESS. `/connections/<code>` is this screen with that credential's form
 * in the panel, so a step's connection is one link away from the step naming it -- and a code past
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
    // A code the walk has not reached, read on its own. A 404 answers nothing and the panel
    // stays shut, which is what an address naming no connection should do.
    const ask = useCallback(
        () => (chosen === null || listed !== null ? Promise.resolve(null) : readConnection(chosen)),
        [chosen, listed],
    )
    const alone = useRead(ask)
    const read = alone.value
    // A row read on its own takes what a check or a save has since made of it, as a listed one does.
    const open = listed ?? (read === null ? null : (fresher[read.code] ?? read))

    // The address is the selection, so a link straight to a connection opens the panel it names.
    useEffect(() => {
        if (chosen !== null) openPanel()
    }, [chosen])

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

    useEffect(() => {
        if (open === null) return
        const schema = kinds?.find((entry) => entry.id === open.kind)?.config_schema ?? null
        return fillPanel(
            [
                {
                    id: 'connection',
                    label: 'Connection',
                    render: () => (
                        <ConnectionForm key={open.code} connection={open} schema={schema} onSaved={held} />
                    ),
                },
            ],
            { screen: 'connections' },
        )
    }, [held, kinds, open])

    const write = useMayWrite('admin')
    const mayWrite = write.may

    useEffect(() => {
        return registerActions([
            // A row this account's role would be refused is a row the palette does not offer.
            ...(mayWrite
                ? [
                      {
                          id: 'connections:new',
                          title: 'New connection',
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
                title: 'Read the connections listing again',
                group: LIST_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload'],
                run: reload,
            },
        ])
    }, [mayWrite, reload])

    const columns = useMemo(() => buildColumns(check, checking, write.why), [check, checking, write.why])

    return (
        <>
            <PageHeader
                title="Connections"
                aside={
                    <>
                        <ApiChip tag="connections" />
                        <Refusable why={write.why}>
                            <Button
                                size="sm"
                                aria-label="New connection"
                                disabled={!write.may}
                                title={write.why}
                                onClick={() => {
                                    setCreating(true)
                                }}
                            >
                                <PlugZap aria-hidden />
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
                emptyMessage="No connections."
            >
                <ListTable
                    columns={columns}
                    rows={rows}
                    rowKey={connectionId}
                    reading={state.reading}
                    next={state.next}
                    onMore={more}
                    noun="connections"
                    onSelect={(row) => {
                        // The row is not another page of history: it is which one is being read.
                        void navigate(connectionPath(row.code), { replace: true })
                    }}
                    selected={(row) => row.code === chosen}
                />
            </PageState>

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

/** The columns, which carry the one thing that is not a plain reading: the check button. */
function buildColumns(
    check: (row: ConnectionOut) => void,
    checking: string | null,
    /** Why a check is shut for this account, or nothing when it is not. */
    shut: string | undefined,
): Column<ConnectionOut>[] {
    return [
        {
            id: 'connection',
            header: 'Connection',
            kind: 'title',
            cell: (row) => <Named row={row} />,
        },
        {
            id: 'health',
            header: 'Health',
            cell: (row) => <Health row={row} />,
        },
        {
            id: 'checked',
            header: 'Checked',
            className: 'text-xs',
            // Nothing rather than an element that draws nothing: a card leaves out the fact a
            // row has none of, and an empty element is a label with a blank beside it.
            cell: (row) => (row.last_check_at === null ? null : <Checked at={row.last_check_at} />),
        },
        {
            id: 'check',
            header: '',
            // The 36px button is the tallest thing on the row, so its own padding is what
            // decides the row's height: `py-1` is the 44px line every other cell fits inside.
            className: 'py-1 text-right',
            cell: (row) => (
                <Refusable why={shut}>
                    <Button
                        variant="outline"
                        size="icon-lg"
                        aria-label={`Check ${row.code}`}
                        disabled={checking === row.code || shut !== undefined}
                        title={shut ?? 'Check now'}
                        onClick={(event) => {
                            // The row opens the panel; this button does one thing and not both.
                            event.stopPropagation()
                            check(row)
                        }}
                    >
                        <RefreshCw className={cn(checking === row.code && 'animate-spin')} aria-hidden />
                    </Button>
                </Refusable>
            ),
        },
    ]
}

/**
 * What a credential is called, the code it is reached by, and which kind it is.
 *
 * THE MARK LEADS AND THE CHIP FOLLOWS. The kind's glyph is what tells a row from its neighbours
 * at a glance and the chip is the word somebody narrows or types by, so the row wears both: the
 * mark ahead of the identity, then the title and the code together, then the kind in words.
 */
function Named({ row }: { row: ConnectionOut }) {
    const heading = headingOf(row)
    const marks = useStore(kindMarks)
    return (
        <span className="flex min-w-0 items-center gap-2">
            <Mark glyph={kindGlyph(row.kind, marks)} />
            <span
                className={cn('truncate font-semibold', !heading.named && 'font-mono')}
                title={heading.title}
            >
                {heading.title}
            </span>
            {heading.code !== null && (
                <span className="truncate font-mono text-xs text-muted-foreground" title={heading.code}>
                    {heading.code}
                </span>
            )}
            <KindChip kind={row.kind} />
        </span>
    )
}

/**
 * Whether this credential answered the last time anything asked it.
 *
 * THE DOT AND THE WORD ARE THE CELL, and the check's own sentence is what reaching it says. A
 * sentence drawn on the row is either a row as tall as the sentence or an ellipsis saying
 * nothing, and the whole of it is on the connection's page either way.
 */
function Health({ row }: { row: ConnectionOut }) {
    const view = healthOf(row)
    // A card has no pointer to hover with, and it opens the page that says the whole of it.
    const cards = useListCards()
    if (view.detail === null || cards) return <HealthSaid view={view} />
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <button
                        type="button"
                        // Reached by a pointer or by the keyboard, and pressing it does what the
                        // row does, because the row is what it stands in.
                        className="rounded-sm focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
                    >
                        <HealthSaid view={view} />
                    </button>
                }
            />
            <TooltipContent side="bottom">{view.detail}</TooltipContent>
        </Tooltip>
    )
}

/** When the last check was made. A row nothing has checked says so in the health cell. */
function Checked({ at }: { at: string }) {
    return (
        <span className="text-muted-foreground" title={formatInstant(at)}>
            {formatRelative(at)}
        </span>
    )
}
