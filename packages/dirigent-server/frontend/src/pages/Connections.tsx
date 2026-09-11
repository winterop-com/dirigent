import { PlugZap, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from 'react'

import { ApiChip } from '@/components/ApiChip'
import { ConnectionForm } from '@/components/connections/ConnectionForm'
import { NewConnection } from '@/components/connections/NewConnection'
import { KindChip } from '@/components/KindChip'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader, PageState } from '@/components/PageState'
import { Refusable } from '@/components/Refusable'
import { sayRefusal } from '@/components/Refusal'
import { Button } from '@/components/ui/button'
import { useMayWrite } from '@/hooks/use-may-write'
import { usePaged } from '@/hooks/use-paged'
import {
    checkConnection,
    connectionsNote,
    healthOf,
    readConnectionKinds,
    readConnections,
    settingsSummary,
    withCheck,
    type ConnectionOut,
    type SurfaceEntry,
} from '@/lib/connections'
import { formatInstant, formatRelative } from '@/lib/format'
import { headingOf, oneLine } from '@/lib/identity'
import { fillPanel, openPanel } from '@/lib/panels'
import { LIST_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'

const connectionId = (row: ConnectionOut) => row.code

/** What each health state fills its dot with. The aliases are index.css's, for what is not a run. */
const TONES: Record<'good' | 'critical', string> = { good: 'var(--good)', critical: 'var(--critical)' }

/**
 * Every credential this instance holds, in code order.
 *
 * A SECRET IS NEVER ON THIS SCREEN. The API redacts every secret field before it answers, and
 * `settingsSummary` is written so that a config which somehow did carry one still could not put
 * it in the row. What a reader learns about a credential is that it is set, and nothing else.
 *
 * A CHECK IS A WRITE, AND THE ROW IS WHAT IT ANSWERS. `POST /connections/{code}/$check` opens
 * the credential, asks the external system, and records the three fields the health column
 * draws -- so the row is updated from the report rather than by reading the listing again, and
 * the row somebody just pressed stays where it was.
 *
 * THE CATALOG IS READ WHEN A FORM NEEDS IT. The kinds and the config schema each one publishes
 * come from `GET /blocks`, which is every installed block as well, so a reader who only looks
 * at the listing never asks for it: opening a row or the dialog is what does.
 */
export function Connections() {
    const [chosen, setChosen] = useState<string | null>(null)
    const [creating, setCreating] = useState(false)
    // What a check or a save has since made of a row, over the page it was read on.
    const [fresher, setFresher] = useState<Record<string, ConnectionOut>>({})
    const [checking, setChecking] = useState<string | null>(null)
    const [kinds, setKinds] = useState<SurfaceEntry[] | null>(null)

    const { state, more, reload } = usePaged(readConnections, connectionId)

    const rows = useMemo(() => state.rows.map((row) => fresher[row.code] ?? row), [fresher, state.rows])
    const open = rows.find((row) => row.code === chosen) ?? null

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
    const wanted = chosen !== null || creating
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
                        setChosen(row.code)
                        openPanel()
                    }}
                    selected={(row) => row.code === chosen}
                />
            </PageState>

            <NewConnection
                open={creating}
                kinds={kinds ?? []}
                onOpenChange={setCreating}
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
            cell: (row) => <Named row={row} />,
        },
        {
            id: 'description',
            header: 'Description',
            cell: (row) => <Said description={row.description} />,
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
            cell: (row) => <Checked row={row} />,
        },
        {
            id: 'check',
            header: '',
            className: 'text-right',
            cell: (row) => (
                <Refusable why={shut}>
                    <Button
                        variant="outline"
                        size="sm"
                        disabled={checking === row.code || shut !== undefined}
                        title={shut}
                        onClick={(event) => {
                            // The row opens the panel; this button does one thing and not both.
                            event.stopPropagation()
                            check(row)
                        }}
                    >
                        {checking === row.code ? 'Checking' : 'Check'}
                    </Button>
                </Refusable>
            ),
        },
    ]
}

/** What a credential is called, the code it is reached by, and what it is pointed at. */
function Named({ row }: { row: ConnectionOut }) {
    const heading = headingOf(row)
    return (
        <div className="min-w-0">
            <span className="flex items-center gap-2">
                <span className={heading.named ? 'font-semibold' : 'font-mono font-semibold'}>
                    {heading.title}
                </span>
                <KindChip kind={row.kind} />
                {heading.code !== null && (
                    <span className="font-mono text-xs text-muted-foreground">{heading.code}</span>
                )}
            </span>
            <p className="max-w-md truncate text-xs text-muted-foreground" title={settingsSummary(row)}>
                {settingsSummary(row)}
            </p>
        </div>
    )
}

/**
 * What a credential says about itself, as the one line a row has space for.
 *
 * IT IS A BLOCK, WHICH IS WHAT MAKES IT TRUNCATE. `max-width` and `overflow` say nothing about
 * an inline box, so the same classes on a span leave the column to grow to the longest
 * description on the page and push the health cells off the side of the table.
 *
 * A CONNECTION THAT SAYS NOTHING DRAWS NOTHING. A dash in the cell is a mark a reader has to
 * stop and read to learn there was nothing to read.
 */
function Said({ description }: { description: string | null }) {
    const text = description === null ? '' : oneLine(description)
    if (text === '') return null
    return (
        <p className="max-w-64 truncate text-xs text-muted-foreground" title={text}>
            {text}
        </p>
    )
}

/** Whether this credential answered the last time anything asked it. */
function Health({ row }: { row: ConnectionOut }) {
    const view = healthOf(row)
    if (view.tone === null) return <span className="text-xs text-faint">never checked</span>
    return (
        <span className="flex items-center gap-2 text-xs">
            <span
                className="status-dot"
                style={{ '--chip': TONES[view.tone] } as CSSProperties}
                aria-hidden
            />
            <span>{view.label}</span>
            {view.detail !== null && (
                <span className="max-w-64 truncate text-muted-foreground" title={view.detail}>
                    {view.detail}
                </span>
            )}
        </span>
    )
}

/** When the last check was made. A row nothing has checked says so in the health cell. */
function Checked({ row }: { row: ConnectionOut }) {
    if (row.last_check_at === null) return null
    return (
        <span className="text-muted-foreground" title={formatInstant(row.last_check_at)}>
            {formatRelative(row.last_check_at)}
        </span>
    )
}
