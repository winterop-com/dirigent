import { KeyRound, RefreshCw, UserPlus } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiChip } from '@/components/ApiChip'
import { ConfirmDialog } from '@/components/ds/ConfirmDialog'
import { AccountTokens } from '@/components/admin/AccountTokens'
import { AdminOnly } from '@/components/admin/AdminOnly'
import { CreateToken } from '@/components/admin/CreateToken'
import { CreateUser } from '@/components/admin/CreateUser'
import { ResetPassword } from '@/components/admin/ResetPassword'
import { Chip } from '@/components/ds/Chip'
import { EntityHeading } from '@/components/ds/EntityHeading'
import { IconButton } from '@/components/ds/IconButton'
import { Instant } from '@/components/Instant'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageHeader } from '@/components/ds/PageHeader'
import { PageState } from '@/components/PageState'
import { Refusal } from '@/components/Refusal'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { usePaged } from '@/hooks/use-paged'
import { useRead } from '@/hooks/use-read'
import { useStore } from '@/hooks/use-store'
import { ApiError, type Problem } from '@/lib/api'
import { authStore, type UserRole } from '@/lib/auth'
import { formatInstant, formatRelative } from '@/lib/format'
import { ICONS } from '@/lib/icons'
import { counted, LABELS } from '@/lib/labels'
import { ADMIN_GROUP, registerActions } from '@/lib/palette'
import { refusalOf } from '@/lib/refusal'
import { closePanel, fillPanel, openPanel } from '@/lib/panels'
import { clearScreenStatus, setScreenStatus } from '@/lib/screen-status'
import {
    accountHeading,
    readTokenCensus,
    readUsers,
    ROLE_HINTS,
    setUserActive,
    tokenCounts,
    updateUser,
    USER_ROLES,
    type UserOut,
} from '@/lib/users'

const userId = (user: UserOut) => user.id

/** What the panel is editing, before it is sent. */
interface Draft {
    name: string
    email: string
    role: UserRole
}

/**
 * Local accounts, with the tokens automation authenticates as each of them under its row.
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
    // The account Deactivate is asking about, and what the server said when it was answered.
    const [deactivating, setDeactivating] = useState<UserOut | null>(null)
    const [deactivateRefused, setDeactivateRefused] = useState<Problem | null>(null)
    const [deactivateBusy, setDeactivateBusy] = useState(false)
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

    const choose = useCallback((user: UserOut) => {
        setChosen(user)
        setDraft({ name: user.name ?? '', email: user.email ?? '', role: user.role })
        setRefusal(null)
        openPanel()
    }, [])

    /** What taking the open row back means here: the form goes, and with it whatever it said. */
    const unchoose = useCallback(() => {
        setChosen(null)
        setRefusal(null)
        closePanel()
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
        return fillPanel(
            [
                {
                    id: 'account',
                    label: LABELS.word.account.label,
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
                                if (active) {
                                    change(setUserActive(chosen.username, true))
                                    return
                                }
                                setDeactivateRefused(null)
                                setDeactivating(chosen)
                            }}
                            onResetPassword={() => {
                                setResetting(chosen.username)
                            }}
                        />
                    ),
                },
            ],
            { screen: 'users' },
        )
    }, [busy, change, chosen, draft, refusal])

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
                    onSelect={choose}
                    selected={(user) => chosen !== null && user.id === chosen.id}
                    onClose={unchoose}
                    rowClassName={(user) => (user.active ? undefined : 'opacity-60')}
                    reading={users.state.reading}
                    next={users.state.next}
                    onMore={users.more}
                    noun={LABELS.word.account.count}
                    under={tokensUnder}
                />
            </PageState>

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
            <ConfirmDialog
                open={deactivating !== null}
                onOpenChange={(next) => {
                    if (!next) setDeactivating(null)
                }}
                ask={LABELS.users.deactivate_ask}
                code={deactivating?.username ?? ''}
                verb={LABELS.action.deactivate}
                busy={deactivateBusy}
                problem={deactivateRefused}
                onConfirm={() => {
                    if (deactivating === null) return
                    setDeactivateBusy(true)
                    setDeactivateRefused(null)
                    void setUserActive(deactivating.username, false)
                        .then(
                            (user) => {
                                setDeactivating(null)
                                setChosen(user)
                                reloadUsers()
                            },
                            (error: unknown) => {
                                setDeactivateRefused(refusalOf(error))
                            },
                        )
                        .finally(() => {
                            setDeactivateBusy(false)
                        })
                }}
            />
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
                                // The row opens the panel; this control does one thing and not both.
                                event.stopPropagation()
                                toggle(user.username)
                            }}
                        />
                        <EntityHeading
                            variant="row-inline"
                            thing={{ code: user.username, name: user.name }}
                            chips={
                                user.active ? undefined : (
                                    <Chip tone="dashed">{LABELS.state.armed.deactivated}</Chip>
                                )
                            }
                        />
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
            cell: (user) => <Chip>{user.role}</Chip>,
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

/**
 * One account: what is true of it, and the two things this screen can change.
 *
 * THE USERNAME IS THE CODE, so the heading is the same one every other panel in this app draws
 * -- the name where there is one, the username in mono either way, and the id beside it.
 *
 * ITS VERBS ARE THE NAME, THE EMAIL, THE ROLE, WHETHER IT IS SWITCHED ON AND A PASSWORD RESET.
 * Its tokens are not here: they stand under its row in the listing, with `New token` on that row.
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
}) {
    const changed =
        (user.name ?? '') !== draft.name || (user.email ?? '') !== draft.email || user.role !== draft.role
    const heading = accountHeading(user)
    return (
        <div className="space-y-4 p-4">
            <div className="space-y-1">
                <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span
                        className={
                            heading.named ? 'text-sm font-semibold' : 'font-mono text-sm font-semibold'
                        }
                    >
                        {heading.title}
                    </span>
                    <Badge variant="outline">{user.role}</Badge>
                    {heading.code !== null && (
                        <span className="font-mono text-xs text-muted-foreground">{heading.code}</span>
                    )}
                    {!user.active && (
                        <span className="text-xs text-muted-foreground">
                            {LABELS.state.armed.deactivated}
                        </span>
                    )}
                </p>
                <p className="text-xs text-faint">
                    {LABELS.word.created.label} <Instant at={user.created_at} /> ·{' '}
                    {user.last_login_at === null ? (
                        LABELS.users.never_signed_in
                    ) : (
                        <>
                            {LABELS.word.last_signed_in.term} <Instant at={user.last_login_at} />
                        </>
                    )}
                </p>
            </div>

            <div className="space-y-1.5">
                <Label htmlFor="panel-name">{LABELS.word.name.label}</Label>
                <Input
                    id="panel-name"
                    value={draft.name}
                    autoComplete="off"
                    onChange={(event) => {
                        onDraft({ ...draft, name: event.target.value })
                    }}
                />
                <p className="text-xs text-faint">{LABELS.users.name_hint(user.username)}</p>
            </div>

            <div className="space-y-1.5">
                <Label htmlFor="panel-email">{LABELS.word.email}</Label>
                <Input
                    id="panel-email"
                    value={draft.email}
                    autoComplete="off"
                    placeholder={LABELS.users.optional}
                    onChange={(event) => {
                        onDraft({ ...draft, email: event.target.value })
                    }}
                />
                <p className="text-xs text-faint">{LABELS.users.email_hint}</p>
            </div>

            <fieldset className="space-y-2">
                <legend className="text-sm font-medium">{LABELS.word.role}</legend>
                {USER_ROLES.map((role) => (
                    <label key={role} className="flex items-start gap-2 text-sm">
                        <input
                            type="radio"
                            name="panel-role"
                            className="mt-1 accent-primary"
                            checked={draft.role === role}
                            onChange={() => {
                                onDraft({ ...draft, role })
                            }}
                        />
                        <span>
                            {role}
                            <span className="block text-xs text-muted-foreground">{ROLE_HINTS[role]}</span>
                        </span>
                    </label>
                ))}
            </fieldset>

            {refusal !== null && <Refusal problem={refusal} />}

            <div className="flex flex-wrap gap-2">
                <Button size="sm" disabled={busy || !changed} onClick={onSave}>
                    {LABELS.action.save.verb}
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
                    {user.active ? LABELS.action.deactivate : LABELS.action.activate}
                </Button>
            </div>

            <div className="flex flex-wrap gap-2">
                <Button variant="outline" size="sm" disabled={busy} onClick={onResetPassword}>
                    {LABELS.users.reset_password}
                </Button>
            </div>
        </div>
    )
}
