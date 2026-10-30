import { KeyRound, RefreshCw, UserPlus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiChip } from '@/components/ApiChip'
import { AccountDialog } from '@/components/admin/AccountDialog'
import { AccountTokens } from '@/components/admin/AccountTokens'
import { AdminOnly } from '@/components/admin/AdminOnly'
import { CreateToken } from '@/components/admin/CreateToken'
import { CreateUser } from '@/components/admin/CreateUser'
import { Chip } from '@/components/ds/Chip'
import { EntityHeading } from '@/components/ds/EntityHeading'
import { IconButton } from '@/components/ds/IconButton'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader } from '@/components/ds/PageHeader'
import { PageState } from '@/components/PageState'
import { Button } from '@/components/ui/button'
import { usePaged } from '@/hooks/use-paged'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@/hooks/use-store'
import { authStore } from '@/lib/auth'
import { formatInstant, formatRelative } from '@/lib/format'
import { ICONS } from '@/lib/icons'
import { counted, LABELS } from '@/lib/labels'
import { ADMIN_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { readTokenCensus, readUsers, tokenCounts, type UserOut } from '@/lib/users'

const userId = (user: UserOut) => user.id

/**
 * Local accounts, with the tokens automation authenticates as each of them under its row.
 *
 * THE LAST-ADMIN GUARD IS THE SERVER'S AND IS RENDERED, NOT PRE-EMPTED. Demoting or
 * deactivating the only active admin is refused with 409 and a sentence naming the account, and
 * that sentence is drawn in the dialog that asked. A guard drawn here would have to work out which
 * accounts are admins and active over whichever page of the listing happens to be loaded.
 *
 * A ROW OPENS A DIALOG. A press on a row opens `AccountDialog`, and a press on its chevron stands
 * its tokens open under it and does nothing else.
 */
export function AdminUsers() {
    return (
        <AdminOnly>
            <Users />
        </AdminOnly>
    )
}

function Users() {
    const [chosen, setChosen] = useState<UserOut | null>(null)
    const [making, setMaking] = useState(false)
    const [minting, setMinting] = useState(false)
    const [mintingFor, setMintingFor] = useState<string | null>(null)
    // Which accounts stand open, and how many times each one's tokens have changed from outside.
    const [opened, setOpened] = useState<ReadonlySet<string>>(() => new Set())
    const [revisions, setRevisions] = useState<Readonly<Record<string, number>>>({})
    const self = useStore(authStore).identity?.username ?? null

    const users = usePaged(
        useCallback((after: string | null) => readUsers(after), []),
        userId,
    )
    const census = useRead(useCallback(() => readTokenCensus(), []))

    const { reload: reloadUsers } = users
    const { again: readCensusAgain } = census

    const [now] = useState(() => Date.now())
    const counts = useMemo(
        () => (census.value === null ? null : tokenCounts(census.value, now)),
        [census.value, now],
    )

    const toggleTokens = useCallback((username: string) => {
        setOpened((current) => {
            const next = new Set(current)
            if (next.has(username)) next.delete(username)
            else next.add(username)
            return next
        })
    }, [])

    /** A token was made for this account: its row opens, and its list and the counts read again. */
    const madeFor = useCallback(
        (username: string) => {
            setOpened((current) => new Set(current).add(username))
            setRevisions((current) => ({ ...current, [username]: (current[username] ?? 0) + 1 }))
            readCensusAgain()
        },
        [readCensusAgain],
    )

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

    useEffect(() => {
        return registerActions([
            {
                id: 'admin:new-user',
                title: LABELS.users.new_user_action,
                group: ADMIN_GROUP,
                screen: true,
                icon: UserPlus,
                keywords: ['user', 'add', 'new'],
                run: () => {
                    setMaking(true)
                },
            },
            {
                id: 'admin:new-token',
                title: LABELS.users.new_token_action,
                group: ADMIN_GROUP,
                screen: true,
                icon: KeyRound,
                keywords: ['api', 'bearer', 'new'],
                run: () => {
                    setMinting(true)
                },
            },
            {
                id: 'admin:reload-users',
                title: LABELS.users.reload_action,
                group: ADMIN_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload'],
                run: () => {
                    reloadUsers()
                    readCensusAgain()
                },
            },
        ])
    }, [readCensusAgain, reloadUsers])

    const tokensUnder = useCallback(
        (user: UserOut) =>
            opened.has(user.username) ? (
                <AccountTokens
                    username={user.username}
                    revision={revisions[user.username] ?? 0}
                    onChanged={readCensusAgain}
                />
            ) : null,
        [opened, readCensusAgain, revisions],
    )

    const columns = useMemo(
        () => userColumns(opened, counts, toggleTokens, setMintingFor),
        [counts, opened, toggleTokens],
    )

    return (
        <>
            <PageHeader
                title={LABELS.screen.users.name}
                aside={
                    <>
                        <ApiChip tag="users" />
                        <Button
                            size="sm"
                            aria-label={LABELS.users.new_account}
                            onClick={() => {
                                setMaking(true)
                            }}
                        >
                            <UserPlus aria-hidden />
                            {LABELS.action.new}
                        </Button>
                    </>
                }
            />

            <PageState
                loading={!users.state.read}
                problem={users.state.problem}
                empty={users.state.rows.length === 0}
                emptyMessage={LABELS.users.accounts_empty}
            >
                <ListTable
                    columns={columns}
                    rows={users.state.rows}
                    rowKey={userId}
                    onSelect={setChosen}
                    selected={(user) => chosen !== null && user.id === chosen.id}
                    rowClassName={(user) => (user.active ? undefined : 'opacity-60')}
                    reading={users.state.reading}
                    next={users.state.next}
                    onMore={users.more}
                    noun={LABELS.word.account.count}
                    under={tokensUnder}
                />
            </PageState>

            {chosen !== null && (
                <AccountDialog
                    key={chosen.id}
                    user={chosen}
                    onChanged={(user) => {
                        setChosen(user)
                        reloadUsers()
                    }}
                    onClose={() => {
                        setChosen(null)
                    }}
                />
            )}
            <CreateUser open={making} onOpenChange={setMaking} onCreated={reloadUsers} />
            <CreateToken
                open={minting}
                onOpenChange={setMinting}
                onCreated={() => {
                    if (self !== null) madeFor(self)
                }}
            />
            {mintingFor !== null && (
                <CreateToken
                    open
                    username={mintingFor}
                    onOpenChange={(next) => {
                        if (!next) setMintingFor(null)
                    }}
                    onCreated={() => {
                        madeFor(mintingFor)
                    }}
                />
            )}
        </>
    )
}

/** The account columns, given which rows stand open and what the row's two controls do. */
function userColumns(
    opened: ReadonlySet<string>,
    counts: ReadonlyMap<string, number> | null,
    toggle: (username: string) => void,
    mint: (username: string) => void,
): Column<UserOut>[] {
    return [
        {
            id: 'account',
            header: LABELS.word.account.label,
            kind: 'title',
            cell: (user) => {
                const open = opened.has(user.username)
                const held = counts?.get(user.username) ?? 0
                return (
                    <span className="flex min-w-0 items-center gap-2">
                        <IconButton
                            icon={ICONS.expand}
                            size="sm"
                            label={
                                open
                                    ? LABELS.users.hide_tokens(user.username)
                                    : LABELS.users.show_tokens(user.username)
                            }
                            aria-expanded={open}
                            className={open ? 'shrink-0 [&_svg]:rotate-90' : 'shrink-0'}
                            onClick={(event) => {
                                // The row opens the dialog; this control does one thing and not both.
                                event.stopPropagation()
                                toggle(user.username)
                            }}
                        />
                        <span className="min-w-0" title={LABELS.users.open_account(user.username)}>
                            <EntityHeading
                                variant="row-inline"
                                thing={{ code: user.username, name: user.name }}
                                chips={
                                    user.active ? undefined : (
                                        <Chip tone="dashed">{LABELS.state.armed.deactivated}</Chip>
                                    )
                                }
                            />
                        </span>
                        {held > 0 && (
                            <span className="shrink-0 text-xs whitespace-nowrap text-faint">
                                {counted(held, LABELS.users.tokens_held)(String(held))}
                            </span>
                        )}
                    </span>
                )
            },
        },
        {
            id: 'role',
            header: LABELS.word.role,
            className: 'text-xs',
            cell: (user) => <span className="text-muted-foreground">{user.role}</span>,
        },
        {
            id: 'seen',
            header: LABELS.word.last_signed_in.label,
            className: 'text-xs',
            cell: (user) => (
                <span className="text-muted-foreground" title={formatInstant(user.last_login_at)}>
                    {user.last_login_at === null ? LABELS.word.never : formatRelative(user.last_login_at)}
                </span>
            ),
        },
        {
            id: 'created',
            header: LABELS.word.created.label,
            className: 'text-xs',
            cell: (user) => (
                <span className="text-muted-foreground" title={formatInstant(user.created_at)}>
                    {formatRelative(user.created_at)}
                </span>
            ),
        },
        {
            id: 'token',
            header: '',
            className: 'text-right',
            cell: (user) => (
                <Button
                    variant="outline"
                    size="xs"
                    aria-label={LABELS.users.new_token_for(user.username)}
                    onClick={(event) => {
                        event.stopPropagation()
                        mint(user.username)
                    }}
                >
                    <ICONS.token aria-hidden />
                    {LABELS.users.new_token}
                </Button>
            ),
        },
    ]
}
