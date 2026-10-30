import { useCallback, useEffect, useMemo, useState } from 'react'

import { ConfirmDialog } from '@/components/ds/ConfirmDialog'
import { Chip } from '@/components/ds/Chip'
import { ListTable, type Column } from '@/components/list/ListTable'
import { PageState } from '@/components/PageState'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { usePaged } from '@/hooks/use-paged'
import { type Problem } from '@/lib/api'
import { formatInstant, formatRelative } from '@/lib/format'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { refusalOf } from '@/lib/refusal'
import {
    isLive,
    readAccountTokens,
    revokedTogether,
    revokeToken,
    sharedNames,
    type TokenOut,
} from '@/lib/users'

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
    const together = revoking === null ? 0 : revokedTogether(state.rows, revoking.name)

    return (
        <div className="flex max-h-96 flex-col" data-account-tokens>
            <PageState
                loading={!state.read}
                problem={state.problem}
                empty={state.rows.length === 0}
                emptyMessage={LABELS.users.tokens_empty}
            >
                <ListTable
                    columns={columns}
                    rows={state.rows}
                    rowKey={tokenId}
                    rowClassName={(token) => (isLive(token, now) ? undefined : 'opacity-60')}
                    reading={state.reading}
                    next={state.next}
                    onMore={more}
                    noun={LABELS.word.token.count}
                />
            </PageState>
            <ConfirmDialog
                open={revoking !== null}
                onOpenChange={(next) => {
                    if (!next) setRevoking(null)
                }}
                title={LABELS.users.revoke_title}
                code={revoking?.name ?? ''}
                consequence={
                    together > 1
                        ? LABELS.users.revoke_consequence_shared(String(together))
                        : LABELS.users.revoke_consequence
                }
                verb={LABELS.action.revoke}
                busy={busy}
                problem={refused}
                onConfirm={() => {
                    if (revoking === null) return
                    setBusy(true)
                    setRefused(null)
                    void revokeToken(revoking.username, revoking.name)
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
                }}
            />
        </div>
    )
}

/** The columns of a token row: what it is called, when it was used and made, and Revoke. */
function tokenColumns(
    shared: ReadonlySet<string>,
    now: number,
    revoke: (token: TokenOut) => void,
): Column<TokenOut>[] {
    return [
        {
            id: 'name',
            header: LABELS.word.token.label,
            kind: 'title',
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
            className: 'text-xs',
            cell: (token) => (
                <span className="text-muted-foreground" title={formatInstant(token.last_used_at)}>
                    {token.last_used_at === null ? LABELS.word.never : formatRelative(token.last_used_at)}
                </span>
            ),
        },
        {
            id: 'created',
            header: LABELS.word.created.label,
            className: 'text-xs',
            cell: (token) => (
                <span className="text-muted-foreground" title={formatInstant(token.created_at)}>
                    {formatRelative(token.created_at)}
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
                        aria-label={LABELS.users.revoke_row(token.name)}
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
