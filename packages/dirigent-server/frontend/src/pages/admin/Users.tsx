import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiChip } from '@/components/ApiChip'
import { Instant } from '@/components/Instant'
import { AccountDialog } from '@/components/admin/AccountDialog'
import { AccountTokens } from '@/components/admin/AccountTokens'
import { AdminOnly } from '@/components/admin/AdminOnly'
import { CreateToken } from '@/components/admin/CreateToken'
import { CreateUser } from '@/components/admin/CreateUser'
import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { DataTable, useTableCell, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { ItemHeading } from '@winterop-com/sokkel-ui/ItemHeading'
import { PageHeader } from '@/components/ds/PageHeader'
import { PageState } from '@winterop-com/sokkel-ui/PageState'
import { refusedRead } from '@/components/Refusal'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { usePaged } from '@/hooks/use-paged'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@winterop-com/sokkel-ui/hooks/use-store'
import { authStore } from '@/lib/auth'
import { LISTING } from '@/lib/design-system'
import { ICONS } from '@/lib/icons'
import { itemOf } from '@/lib/identity'
import { counted, LABELS } from '@/lib/labels'
import { rowsRead } from '@/lib/paging'
import { ADMIN_GROUP, registerActions } from '@/lib/palette'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import { readTokenCensus, readUsers, tokenCounts, type UserOut } from '@/lib/users'

const userId = (user: UserOut) => user.id
const usernameOf = (user: UserOut) => user.username

/** Every account opens onto its tokens, and an account holding none says so when opened. */
const opens = () => true

/**
 * Local accounts, with the tokens automation authenticates as each of them under its row.
 *
 * THE LAST-ADMIN GUARD IS THE SERVER'S AND IS RENDERED, NOT PRE-EMPTED. Demoting or
 * deactivating the only active admin is refused with 409 and a sentence naming the account, and
 * that sentence is drawn in the dialog that asked. A guard drawn here would have to work out which
 * accounts are admins and active over whichever page of the listing happens to be loaded.
 *
 * A ROW OPENS A DIALOG. A press on a row, or Enter on it, opens `AccountDialog`; its chevron, or
 * the right arrow, stands its tokens open under it as the row's detail and does nothing else.
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
                icon: ICONS.create_user,
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
                icon: ICONS.token,
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
                icon: ICONS.refresh,
                keywords: ['refresh', 'reload'],
                run: () => {
                    reloadUsers()
                    readCensusAgain()
                },
            },
        ])
    }, [readCensusAgain, reloadUsers])

    const tokensUnder = useCallback(
        (user: UserOut) => (
            <AccountTokens
                username={user.username}
                revision={revisions[user.username] ?? 0}
                onChanged={readCensusAgain}
            />
        ),
        [readCensusAgain, revisions],
    )

    const columns = useMemo(() => userColumns(counts, setMintingFor), [counts])

    return (
        <>
            <PageHeader
                title={LABELS.screen.users.name}
                lead={<ApiChip tag="users" />}
                primary={{
                    id: 'new',
                    label: LABELS.users.new_account,
                    face: LABELS.action.new,
                    onSelect: () => {
                        setMaking(true)
                    },
                }}
            />

            <PageState loading={!users.state.read} {...refusedRead(users.state.problem)} empty={false}>
                <DataTable
                    {...LISTING}
                    columns={columns}
                    rows={users.state.rows}
                    rowKey={usernameOf}
                    onOpen={setChosen}
                    opened={(user) => chosen !== null && user.id === chosen.id}
                    detail={tokensUnder}
                    hasDetail={opens}
                    expandLabel={(user, open) =>
                        open
                            ? LABELS.users.hide_tokens(user.username)
                            : LABELS.users.show_tokens(user.username)
                    }
                    rowTone={(user) => (user.active ? undefined : 'muted')}
                    expanded={opened}
                    onExpandedChange={setOpened}
                    hasMore={users.state.next !== null}
                    loading={users.state.reading}
                    onLoadMore={users.more}
                    foot={rowsRead(
                        users.state.rows.length,
                        LABELS.word.account.count,
                        users.state.next !== null,
                    )}
                    empty={LABELS.users.accounts_empty}
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

/** The account columns, given how many live tokens each account holds and what New token does. */
function userColumns(
    counts: ReadonlyMap<string, number> | null,
    mint: (username: string) => void,
): DataColumn<UserOut>[] {
    return [
        {
            id: 'account',
            header: LABELS.word.account.label,
            width: 'content',
            minWidth: '14rem',
            maxWidth: '22rem',
            stackTitle: 'free',
            cell: (user) => <Account user={user} held={counts?.get(user.username) ?? 0} />,
        },
        {
            id: 'role',
            header: LABELS.word.role,
            width: 'minmax(4rem,1fr)',
            cell: (user) => <span className="text-xs text-muted-foreground">{user.role}</span>,
        },
        {
            id: 'seen',
            header: LABELS.word.last_signed_in.label,
            width: 'minmax(5.5rem,1fr)',
            cell: (user) =>
                user.last_login_at === null ? (
                    <span className="text-xs text-muted-foreground">{LABELS.word.never}</span>
                ) : (
                    <Instant className="text-xs text-muted-foreground" at={user.last_login_at} />
                ),
        },
        {
            id: 'created',
            header: LABELS.word.created.label,
            width: 'minmax(4.5rem,1fr)',
            cell: (user) => <Instant className="text-xs text-muted-foreground" at={user.created_at} />,
        },
        {
            id: 'token',
            header: '',
            width: '6.5rem',
            align: 'end',
            stackLabel: false,
            cell: (user) => (
                <Button
                    variant="outline"
                    size="sm"
                    aria-label={LABELS.users.new_token_for(user.username)}
                    onClick={() => {
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

/** An account's username and name, beside each other in a row and the name over the username on a card, with how many live tokens it holds. */
function Account({ user, held }: { user: UserOut; held: number }) {
    const { stacked } = useTableCell()
    return (
        <span className="flex min-w-0 items-center gap-2">
            <span className="min-w-0" title={LABELS.users.open_account(user.username)}>
                <ItemHeading
                    {...itemOf({ code: user.username, name: user.name })}
                    variant={stacked ? 'stacked' : 'inline'}
                    as="span"
                    chips={
                        user.active ? undefined : <Chip tone="absent">{LABELS.state.armed.deactivated}</Chip>
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
}
