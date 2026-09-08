import { KeyRound, RefreshCw, UserPlus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiChip } from '@/components/ApiChip'
import { AdminOnly } from '@/components/admin/AdminOnly'
import { CreateToken } from '@/components/admin/CreateToken'
import { CreateUser } from '@/components/admin/CreateUser'
import { ResetPassword } from '@/components/admin/ResetPassword'
import { Instant } from '@/components/Instant'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader, PageState } from '@/components/PageState'
import { Refusal } from '@/components/Refusal'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { usePaged } from '@/hooks/use-paged'
import { ApiError, type Problem } from '@/lib/api'
import type { UserRole } from '@/lib/auth'
import { formatInstant, formatRelative } from '@/lib/format'
import { ADMIN_GROUP, registerActions } from '@/lib/palette'
import { fillPanel, openPanel } from '@/lib/panels'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import {
    accountHeading,
    readTokens,
    readUsers,
    revokeToken,
    ROLE_HINTS,
    setUserActive,
    updateUser,
    USER_ROLES,
    type TokenOut,
    type UserOut,
} from '@/lib/users'

const userId = (user: UserOut) => user.id
const tokenId = (token: TokenOut) => token.id

/** What the panel is editing, before it is sent. */
interface Draft {
    name: string
    email: string
    role: UserRole
}

/**
 * Local accounts and the tokens automation authenticates with.
 *
 * THE LAST-ADMIN GUARD IS THE SERVER'S AND IS RENDERED, NOT PRE-EMPTED. Demoting or
 * deactivating the only active admin is refused with 409 and a sentence naming the account, and
 * that sentence is drawn in the panel beside the control that asked for it. A guard drawn here
 * would have to work out "which accounts are admins, and which are active" over whichever page
 * of the listing happens to be loaded, and would be wrong the moment somebody else made a
 * change in another tab. A toast is the wrong place for it too: it is an answer to the button
 * that was just pressed, and it belongs beside that button.
 *
 * THE PANEL IS WHERE A ROW IS CHANGED. A table of accounts with a menu on every row is a table
 * whose rows are mostly controls; the panel already exists, is the screen's to fill, and has
 * room for the role each account holds to be explained rather than abbreviated.
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
    const [draft, setDraft] = useState<Draft>({ name: '', email: '', role: 'viewer' })
    const [refusal, setRefusal] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)
    const [making, setMaking] = useState(false)
    const [minting, setMinting] = useState(false)
    const [mintingFor, setMintingFor] = useState<string | null>(null)
    const [resetting, setResetting] = useState<string | null>(null)
    const [tokenRefusal, setTokenRefusal] = useState<Problem | null>(null)

    const users = usePaged(
        useCallback((after: string | null) => readUsers(after), []),
        userId,
    )
    const tokens = usePaged(
        useCallback((after: string | null) => readTokens(after), []),
        tokenId,
    )

    const { reload: reloadUsers } = users
    const { reload: reloadTokens } = tokens

    const choose = useCallback((user: UserOut) => {
        setChosen(user)
        setDraft({ name: user.name ?? '', email: user.email ?? '', role: user.role })
        setRefusal(null)
        openPanel()
    }, [])

    /** Carry out one change to the chosen account, and hold whatever the server said about it. */
    const change = useCallback(
        (work: Promise<UserOut>) => {
            setBusy(true)
            setRefusal(null)
            void work
                .then(
                    (user) => {
                        setChosen(user)
                        setDraft({ name: user.name ?? '', email: user.email ?? '', role: user.role })
                        reloadUsers()
                    },
                    (error: unknown) => {
                        setRefusal(error instanceof ApiError ? error.problem : null)
                    },
                )
                .finally(() => {
                    setBusy(false)
                })
        },
        [reloadUsers],
    )

    useEffect(() => {
        setScreenStatus({ note: null, tone: 'quiet', identifier: null })
        return clearScreenStatus
    }, [])

    useEffect(() => {
        if (chosen === null) return
        return fillPanel([
            {
                id: 'account',
                label: 'Account',
                render: () => (
                    <AccountPanel
                        user={chosen}
                        draft={draft}
                        busy={busy}
                        refusal={refusal}
                        onDraft={setDraft}
                        onSave={() => {
                            change(
                                updateUser(chosen.username, {
                                    name: draft.name.trim() === '' ? null : draft.name.trim(),
                                    email: draft.email.trim() === '' ? null : draft.email.trim(),
                                    role: draft.role,
                                }),
                            )
                        }}
                        onActive={(active) => {
                            change(setUserActive(chosen.username, active))
                        }}
                        onResetPassword={() => {
                            setResetting(chosen.username)
                        }}
                        onMintToken={() => {
                            setMintingFor(chosen.username)
                        }}
                    />
                ),
            },
        ], { screen: 'users' })
    }, [busy, change, chosen, draft, refusal])

    useEffect(() => {
        return registerActions([
            {
                id: 'admin:new-user',
                title: 'Create an account',
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
                title: 'Mint an automation token',
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
                title: 'Read the accounts listing again',
                group: ADMIN_GROUP,
                screen: true,
                icon: RefreshCw,
                keywords: ['refresh', 'reload'],
                run: () => {
                    reloadUsers()
                    reloadTokens()
                },
            },
        ])
    }, [reloadTokens, reloadUsers])

    const columns = useMemo(() => userColumns(choose), [choose])
    const tokenColumns = useMemo(
        () =>
            tokenRows((token) => {
                setTokenRefusal(null)
                void revokeToken(token.username, token.name).then(
                    () => {
                        reloadTokens()
                    },
                    (error: unknown) => {
                        setTokenRefusal(error instanceof ApiError ? error.problem : null)
                    },
                )
            }),
        [reloadTokens],
    )

    return (
        <>
            <PageHeader
                title="Users and tokens"
                aside={
                    <>
                        <ApiChip tag="users" />
                        <Button
                            size="sm"
                            onClick={() => {
                                setMaking(true)
                            }}
                        >
                            <UserPlus aria-hidden />
                            New account
                        </Button>
                    </>
                }
            />

            <section className="space-y-2">
                <h2 className="text-sm font-semibold">Accounts</h2>
                <PageState
                    loading={!users.state.read}
                    problem={users.state.problem}
                    empty={users.state.rows.length === 0}
                    emptyMessage="No accounts."
                >
                    <ListTable
                        columns={columns}
                        rows={users.state.rows}
                        rowKey={userId}
                        onSelect={choose}
                        selected={(user) => chosen !== null && user.id === chosen.id}
                        rowClassName={(user) => (user.active ? undefined : 'opacity-60')}
                        reading={users.state.reading}
                        next={users.state.next}
                        onMore={users.more}
                        noun="accounts"
                    />
                </PageState>
            </section>

            <section className="mt-8 space-y-2">
                <div className="flex items-center justify-between gap-4">
                    <div className="space-y-1">
                        <h2 className="text-sm font-semibold">Tokens</h2>
                        <p className="text-muted-foreground text-sm">A session is never listed here.</p>
                    </div>
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                            setMinting(true)
                        }}
                    >
                        <KeyRound aria-hidden />
                        New token
                    </Button>
                </div>

                {tokenRefusal !== null && <Refusal problem={tokenRefusal} />}

                <PageState
                    loading={!tokens.state.read}
                    problem={tokens.state.problem}
                    empty={tokens.state.rows.length === 0}
                    emptyMessage="No tokens."
                >
                    <ListTable
                        columns={tokenColumns}
                        rows={tokens.state.rows}
                        rowKey={tokenId}
                        rowClassName={(token) => (token.revoked_at === null ? undefined : 'opacity-60')}
                        reading={tokens.state.reading}
                        next={tokens.state.next}
                        onMore={tokens.more}
                        noun="tokens"
                    />
                </PageState>
            </section>

            <CreateUser open={making} onOpenChange={setMaking} onCreated={reloadUsers} />
            <CreateToken open={minting} onOpenChange={setMinting} onCreated={reloadTokens} />
            {mintingFor !== null && (
                <CreateToken
                    open
                    username={mintingFor}
                    onOpenChange={(next) => {
                        if (!next) setMintingFor(null)
                    }}
                    onCreated={reloadTokens}
                />
            )}
            {resetting !== null && (
                <ResetPassword
                    open
                    username={resetting}
                    onOpenChange={(next) => {
                        if (!next) setResetting(null)
                    }}
                    onDone={reloadUsers}
                />
            )}
        </>
    )
}

/** The account columns, given what selecting a row does. */
function userColumns(choose: (user: UserOut) => void): Column<UserOut>[] {
    return [
        {
            id: 'username',
            header: 'Username',
            cell: (user) => (
                <button
                    type="button"
                    className="hover:text-primary text-left text-sm font-medium underline-offset-4 hover:underline"
                    onClick={() => {
                        choose(user)
                    }}
                >
                    {user.username}
                </button>
            ),
        },
        {
            id: 'name',
            header: 'Name',
            cell: (user) => (user.name === null ? null : <span className="text-sm">{user.name}</span>),
        },
        {
            id: 'role',
            header: 'Role',
            cell: (user) => <Badge variant="outline">{user.role}</Badge>,
        },
        {
            id: 'active',
            header: 'Active',
            cell: (user) =>
                user.active ? (
                    <span className="text-good text-xs">active</span>
                ) : (
                    <span className="text-muted-foreground text-xs">deactivated</span>
                ),
        },
        {
            id: 'seen',
            header: 'Last signed in',
            className: 'text-xs',
            cell: (user) => (
                <span className="text-muted-foreground" title={formatInstant(user.last_login_at)}>
                    {user.last_login_at === null ? 'never' : formatRelative(user.last_login_at)}
                </span>
            ),
        },
        {
            id: 'created',
            header: 'Created',
            className: 'text-xs',
            cell: (user) => (
                <span className="text-muted-foreground" title={formatInstant(user.created_at)}>
                    {formatRelative(user.created_at)}
                </span>
            ),
        },
    ]
}

/** The token columns, given what revoking one does. */
function tokenRows(revoke: (token: TokenOut) => void): Column<TokenOut>[] {
    return [
        {
            id: 'account',
            header: 'Account',
            className: 'font-mono text-xs',
            cell: (token) => <span>{token.username}</span>,
        },
        {
            id: 'name',
            header: 'Name',
            cell: (token) => <span className="text-sm font-medium">{token.name}</span>,
        },
        {
            id: 'prefix',
            header: 'Prefix',
            className: 'font-mono text-xs',
            cell: (token) => <span className="text-muted-foreground">{token.prefix}</span>,
        },
        {
            id: 'created',
            header: 'Created',
            className: 'text-xs',
            cell: (token) => (
                <span className="text-muted-foreground" title={formatInstant(token.created_at)}>
                    {formatRelative(token.created_at)}
                </span>
            ),
        },
        {
            id: 'used',
            header: 'Last used',
            className: 'text-xs',
            cell: (token) => (
                <span className="text-muted-foreground" title={formatInstant(token.last_used_at)}>
                    {token.last_used_at === null ? 'never' : formatRelative(token.last_used_at)}
                </span>
            ),
        },
        {
            id: 'revoke',
            header: '',
            className: 'text-right',
            cell: (token) =>
                token.revoked_at === null ? (
                    <Button
                        variant="ghost"
                        size="xs"
                        className="destructive-action"
                        aria-label={`Revoke ${token.name}`}
                        onClick={() => {
                            revoke(token)
                        }}
                    >
                        Revoke
                    </Button>
                ) : (
                    <span className="text-muted-foreground text-xs" title={formatInstant(token.revoked_at)}>
                        revoked
                    </span>
                ),
        },
    ]
}

/**
 * One account: what is true of it, and the two things this screen can change.
 *
 * THE USERNAME IS THE CODE, so the heading is the same one every other panel in this app draws
 * -- the name where there is one, the username in mono either way, and the id beside it.
 *
 * ITS VERBS ARE THE NAME, THE EMAIL, THE ROLE, WHETHER IT IS SWITCHED ON, A PASSWORD RESET AND
 * A TOKEN. The tokens themselves are not drawn here: the table below the listing carries every
 * token this instance holds with the account it authenticates as.
 *
 * A FACT IS A FACT AND A CONTROL IS A VERB. What the account signs in as, when it was made and
 * when it was last seen are read, and nothing else here is drawn as a control.
 */
function AccountPanel({
    user,
    draft,
    busy,
    refusal,
    onDraft,
    onSave,
    onActive,
    onResetPassword,
    onMintToken,
}: {
    user: UserOut
    draft: Draft
    busy: boolean
    /** What the server said about the last thing this panel asked for. */
    refusal: Problem | null
    onDraft: (draft: Draft) => void
    onSave: () => void
    onActive: (active: boolean) => void
    onResetPassword: () => void
    onMintToken: () => void
}) {
    const changed =
        (user.name ?? '') !== draft.name ||
        (user.email ?? '') !== draft.email ||
        user.role !== draft.role
    const heading = accountHeading(user)
    return (
        <div className="space-y-4 p-4">
            <div className="space-y-1">
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className={heading.named ? 'text-sm font-semibold' : 'font-mono text-sm font-semibold'}>
                        {heading.title}
                    </span>
                    <Badge variant="outline">{user.role}</Badge>
                    {heading.code !== null && (
                        <span className="text-muted-foreground font-mono text-xs">{heading.code}</span>
                    )}
                    {!user.active && <span className="text-muted-foreground text-xs">deactivated</span>}
                </p>
                <p className="text-faint text-xs">
                    Created <Instant at={user.created_at} /> ·{' '}
                    {user.last_login_at === null ? (
                        'never signed in'
                    ) : (
                        <>
                            last signed in <Instant at={user.last_login_at} />
                        </>
                    )}
                </p>
            </div>

            <div className="space-y-1.5">
                <Label htmlFor="panel-name">Name</Label>
                <Input
                    id="panel-name"
                    value={draft.name}
                    autoComplete="off"
                    placeholder="What to call this account on screen"
                    onChange={(event) => {
                        onDraft({ ...draft, name: event.target.value })
                    }}
                />
                <p className="text-faint text-xs">
                    Display only. This account signs in as {user.username}, and that is what every
                    reference to it is by.
                </p>
            </div>

            <div className="space-y-1.5">
                <Label htmlFor="panel-email">Email</Label>
                <Input
                    id="panel-email"
                    value={draft.email}
                    autoComplete="off"
                    placeholder="Optional"
                    onChange={(event) => {
                        onDraft({ ...draft, email: event.target.value })
                    }}
                />
                <p className="text-faint text-xs">Unique across accounts.</p>
            </div>

            <fieldset className="space-y-2">
                <legend className="text-sm font-medium">Role</legend>
                {USER_ROLES.map((role) => (
                    <label key={role} className="flex items-start gap-2 text-sm">
                        <input
                            type="radio"
                            name="panel-role"
                            className="accent-primary mt-1"
                            checked={draft.role === role}
                            onChange={() => {
                                onDraft({ ...draft, role })
                            }}
                        />
                        <span>
                            {role}
                            <span className="text-muted-foreground block text-xs">{ROLE_HINTS[role]}</span>
                        </span>
                    </label>
                ))}
            </fieldset>

            {refusal !== null && <Refusal problem={refusal} />}

            <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={busy || !changed} onClick={onSave}>
                    Save
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    className={user.active ? 'destructive-action' : undefined}
                    disabled={busy}
                    onClick={() => {
                        onActive(!user.active)
                    }}
                >
                    {user.active ? 'Deactivate' : 'Activate'}
                </Button>
            </div>

            <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" disabled={busy} onClick={onResetPassword}>
                    Reset password
                </Button>
                <Button variant="outline" size="sm" disabled={busy} onClick={onMintToken}>
                    New token
                </Button>
            </div>
        </div>
    )
}
