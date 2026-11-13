import { useCallback, useEffect, useMemo, useState } from 'react'

import { ConfirmDialog } from '@winterop-com/sokkel-ui/DialogShell'
import { ProblemLine } from '@winterop-com/sokkel-ui/Problem'
import { Instant } from '@/components/Instant'
import { Question } from '@/components/Question'
import { refusedTable } from '@/components/Refusal'
import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { DataTable, type DataColumn } from '@winterop-com/sokkel-ui/DataTable'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@winterop-com/sokkel-ui/primitives/tooltip'
import { usePaged } from '@/hooks/use-paged'
import { type Problem } from '@/lib/api'
import { formatInstant, formatRelative } from '@/lib/format'
import { ICONS } from '@/lib/icons'
import { DIALOG_WORDS } from '@/lib/library-words'
import { LABELS } from '@/lib/labels'
import { rowsRead } from '@/lib/paging'
import { refusalLine, refusalOf } from '@/lib/refusal'
import { isLive, readAccountTokens, revokeToken, sharedNames, type TokenOut } from '@/lib/users'

const tokenId = (token: TokenOut) => token.id

/**
 * The tokens one account holds, under that account's row.
 *
 * READ WHEN IT IS OPENED, on a cursor of its own, and capped in height with its heading stuck, so
 * an account holding hundreds leaves every other account where it was. `revision` says something
 * outside this list changed what it holds.
 */
export function AccountTokens({
    username,
    revision,
    onChanged,
}: {
    username: string
    revision: number
    /** Called when a token was revoked, so a count kept outside this list can read itself again. */
    onChanged: () => void
}) {
    const read = useCallback((after: string | null) => readAccountTokens(username, after), [username])
    const { state, more, reload } = usePaged(read, tokenId)

    useEffect(() => {
        if (revision > 0) reload()
    }, [reload, revision])

    const [revoking, setRevoking] = useState<TokenOut | null>(null)
    const [refused, setRefused] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const [now] = useState(() => Date.now())
    const shared = useMemo(() => sharedNames(state.rows, now), [now, state.rows])
    const columns = useMemo(
        () =>
            tokenColumns(shared, now, (token) => {
                setRefused(null)
                setRevoking(token)
            }),
        [now, shared],
    )

    const rows = state.problem === null ? state.rows : []
    return (
        <div className="flex max-h-96 flex-col" data-account-tokens>
            <DataTable
                variant="list"
                columns={columns}
                rows={rows}
                rowKey={tokenId}
                hasMore={state.problem === null && state.next !== null}
                loading={state.reading}
                onLoadMore={more}
                {...refusedTable(state.problem, reload)}
                foot={
                    rows.length === 0
                        ? undefined
                        : rowsRead(rows.length, LABELS.word.token.count, state.next !== null)
                }
                empty={LABELS.users.tokens_empty}
                columnHeads={rows.length > 0}
                rowTone={(token) => (isLive(token, now) ? undefined : 'muted')}
                resizable={false}
            />
            <ConfirmDialog
                open={revoking !== null}
                onOpenChange={(next) => {
                    if (!next) setRevoking(null)
                }}
                question={
                    <Question
                        ask={LABELS.users.revoke_ask}
                        code={revoking === null ? '' : tokenSaid(revoking, shared, now)}
                    />
                }
                confirm={{
                    label: LABELS.action.revoke,
                    onConfirm: () => {
                        if (revoking === null) return
                        setBusy(true)
                        setRefused(null)
                        void revokeToken(revoking.id)
                            .then(
                                () => {
                                    setRevoking(null)
                                    reload()
                                    onChanged()
                                },
                                (error: unknown) => {
                                    setRefused(refusalOf(error))
                                },
                            )
                            .finally(() => {
                                setBusy(false)
                            })
                    },
                    destructive: true,
                    busy: busy,
                }}
                words={DIALOG_WORDS}
                status={refused === null ? undefined : <ProblemLine>{refusalLine(refused)}</ProblemLine>}
            />
        </div>
    )
}

/** What the token is called, with its prefix where the name has stopped telling it from another. */
function tokenSaid(token: TokenOut, shared: ReadonlySet<string>, now: number): string {
    return shared.has(token.name) && isLive(token, now)
        ? `${token.name} ${LABELS.users.token_prefix(token.prefix)}`
        : token.name
}

/** The columns of a token row: what it is called, when it was used and made, and Revoke. */
function tokenColumns(
    shared: ReadonlySet<string>,
    now: number,
    revoke: (token: TokenOut) => void,
): DataColumn<TokenOut>[] {
    return [
        {
            id: 'name',
            header: LABELS.word.token.label,
            width: 'content',
            maxWidth: '24rem',
            cell: (token) => (
                <span className="flex min-w-0 items-center gap-2">
                    <ICONS.token className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                    <span className="truncate font-mono text-xs font-medium" title={token.name}>
                        {token.name}
                    </span>
                    {shared.has(token.name) && isLive(token, now) && <Prefix prefix={token.prefix} />}
                    {token.expires_at !== null && <Expiry at={token.expires_at} now={now} />}
                </span>
            ),
        },
        {
            id: 'used',
            header: LABELS.users.last_used_column,
            width: 'minmax(5rem,1fr)',
            cell: (token) =>
                token.last_used_at === null ? (
                    <span className="text-xs text-muted-foreground">{LABELS.word.never}</span>
                ) : (
                    <Instant className="text-xs text-muted-foreground" at={token.last_used_at} />
                ),
        },
        {
            id: 'created',
            header: LABELS.word.created.label,
            width: 'minmax(4.5rem,1fr)',
            cell: (token) => <Instant className="text-xs text-muted-foreground" at={token.created_at} />,
        },
        {
            id: 'revoke',
            header: '',
            width: '6rem',
            align: 'end',
            stackLabel: false,
            cell: (token) =>
                token.revoked_at === null ? (
                    <Button
                        variant="ghost"
                        size="xs"
                        destructiveHover
                        aria-label={LABELS.users.revoke_row(tokenSaid(token, shared, now))}
                        onClick={() => {
                            revoke(token)
                        }}
                    >
                        {LABELS.action.revoke}
                    </Button>
                ) : (
                    <span className="text-xs text-muted-foreground" title={formatInstant(token.revoked_at)}>
                        {LABELS.state.armed.revoked}
                    </span>
                ),
        },
    ]
}

/** The head of the secret, drawn only where the name has stopped telling two tokens apart. */
function Prefix({ prefix }: { prefix: string }) {
    return (
        <Tooltip>
            <TooltipTrigger render={<span tabIndex={0} className="shrink-0 font-mono text-xs text-faint" />}>
                {LABELS.users.token_prefix(prefix)}
            </TooltipTrigger>
            <TooltipContent>{LABELS.users.token_prefix_tip}</TooltipContent>
        </Tooltip>
    )
}

/** When a token stops working, or stopped, on the instant's own hover. */
function Expiry({ at, now }: { at: string; now: number }) {
    const when = formatRelative(at)
    return (
        <Chip title={formatInstant(at)}>
            {Date.parse(at) > now ? LABELS.users.token_expires(when) : LABELS.users.token_expired(when)}
        </Chip>
    )
}
