import { useRef, useState } from 'react'
import { toast } from 'sonner'

import { Instant } from '@/components/Instant'
import { Refusal, RefusalLine } from '@/components/Refusal'
import { RoleSelect } from '@/components/admin/RoleSelect'
import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { ConfirmDialog } from '@winterop-com/sokkel-ui/DialogShell'
import { Question } from '@/components/Question'
import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { ItemHeading } from '@winterop-com/sokkel-ui/ItemHeading'
import { DescriptionList } from '@winterop-com/sokkel-ui/DescriptionList'
import { Field } from '@winterop-com/sokkel-ui/Field'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import { Input } from '@winterop-com/sokkel-ui/primitives/input'
import { type Problem } from '@/lib/api'
import { type UserRole } from '@/lib/auth'
import { ICONS } from '@/lib/icons'
import { DIALOG_WORDS } from '@/lib/design-system'
import { itemOf } from '@/lib/identity'
import { LABELS } from '@/lib/labels'
import { local, refusalOf } from '@/lib/refusal'
import {
    MIN_PASSWORD_LENGTH,
    resetPassword,
    ROLE_HINTS,
    setUserActive,
    updateUser,
    type UserOut,
} from '@/lib/users'

/** What the edit state holds, before it is sent. */
interface Draft {
    name: string
    email: string
    role: UserRole
}

function draftOf(user: UserOut): Draft {
    return { name: user.name ?? '', email: user.email ?? '', role: user.role }
}

/**
 * One account, shown first and edited second, in one dialog over the listing.
 *
 * Edit turns the same surface into its form, and Cancel, Escape and a saved edit turn it back.
 * Deactivate and Reset password raise `ConfirmDialog` over it. The last-admin guard is the server's,
 * so its sentence is drawn in whichever of these asked.
 */
export function AccountDialog({
    user,
    onChanged,
    onClose,
}: {
    user: UserOut
    /** Called with what the server answered, so the row behind updates. */
    onChanged: (user: UserOut) => void
    onClose: () => void
}) {
    const [editing, setEditing] = useState(false)
    const [draft, setDraft] = useState<Draft>(() => draftOf(user))
    const [busy, setBusy] = useState(false)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [deactivating, setDeactivating] = useState(false)
    const [resetting, setResetting] = useState(false)
    const editButton = useRef<HTMLButtonElement>(null)

    const changed =
        (user.name ?? '') !== draft.name || (user.email ?? '') !== draft.email || user.role !== draft.role

    const heading = (
        <ItemHeading
            {...itemOf({ code: user.username, name: user.name })}
            size="dialog"
            lead={editing ? LABELS.action.edit : undefined}
            chips={user.active ? undefined : <Chip tone="absent">{LABELS.state.armed.deactivated}</Chip>}
        />
    )

    /** Carry out one change, hold what the server said, and call `done` when it was taken. */
    const change = (work: Promise<UserOut>, done?: () => void) => {
        setBusy(true)
        setProblem(null)
        void work
            .then(
                (next) => {
                    onChanged(next)
                    done?.()
                },
                (error: unknown) => {
                    setProblem(refusalOf(error))
                },
            )
            .finally(() => {
                setBusy(false)
            })
    }

    return (
        <>
            {editing ? (
                <DialogShell
                    words={DIALOG_WORDS}
                    open
                    closeOnOutsidePress={false}
                    onOpenChange={(next) => {
                        if (!next) {
                            setProblem(null)
                            setEditing(false)
                        }
                    }}
                    title={heading}
                    confirm={{
                        label: LABELS.action.save.verb,
                        busy,
                        busyLabel: LABELS.action.save.busy,
                        why: changed ? undefined : LABELS.users.nothing_to_save,
                        onConfirm: () => {
                            change(
                                updateUser(user.username, {
                                    name: draft.name.trim() === '' ? null : draft.name.trim(),
                                    email: draft.email.trim() === '' ? null : draft.email.trim(),
                                    role: draft.role,
                                }),
                                () => {
                                    setEditing(false)
                                },
                            )
                        },
                    }}
                >
                    <div className="grid gap-4 sm:grid-cols-2">
                        <Field id="account-name" label={LABELS.word.name.label}>
                            <Input
                                id="account-name"
                                value={draft.name}
                                autoComplete="off"
                                onChange={(event) => {
                                    setDraft({ ...draft, name: event.target.value })
                                }}
                            />
                        </Field>
                        <Field id="account-email" label={LABELS.word.email}>
                            <Input
                                id="account-email"
                                value={draft.email}
                                autoComplete="off"
                                onChange={(event) => {
                                    setDraft({ ...draft, email: event.target.value })
                                }}
                            />
                        </Field>
                    </div>
                    <Field id="account-role" label={LABELS.word.role}>
                        <RoleSelect
                            id="account-role"
                            value={draft.role}
                            onChange={(role) => {
                                setDraft({ ...draft, role })
                            }}
                        />
                    </Field>
                    {problem !== null && <Refusal problem={problem} />}
                </DialogShell>
            ) : (
                <DialogShell
                    words={DIALOG_WORDS}
                    open
                    onOpenChange={(next) => {
                        if (!next) onClose()
                    }}
                    initialFocus={editButton}
                    title={heading}
                    footer={
                        <Button
                            variant="outline"
                            size="sm"
                            className={user.active ? 'destructive-action' : undefined}
                            disabled={busy}
                            onClick={() => {
                                setProblem(null)
                                if (user.active) setDeactivating(true)
                                else change(setUserActive(user.username, true))
                            }}
                        >
                            {user.active ? <ICONS.deactivate aria-hidden /> : <ICONS.activate aria-hidden />}
                            {user.active ? LABELS.action.deactivate : LABELS.action.activate}
                        </Button>
                    }
                    actions={
                        <>
                            <Button
                                variant="outline"
                                size="sm"
                                disabled={busy}
                                onClick={() => {
                                    setResetting(true)
                                }}
                            >
                                <ICONS.token aria-hidden />
                                {LABELS.action.asks(LABELS.users.reset_password)}
                            </Button>
                            <Button
                                ref={editButton}
                                size="sm"
                                disabled={busy}
                                onClick={() => {
                                    setProblem(null)
                                    setDraft(draftOf(user))
                                    setEditing(true)
                                }}
                            >
                                <ICONS.edit aria-hidden />
                                {LABELS.action.edit}
                            </Button>
                        </>
                    }
                >
                    <AccountFacts user={user} />
                    {problem !== null && !deactivating && <Refusal problem={problem} />}
                </DialogShell>
            )}

            <ConfirmDialog
                open={deactivating}
                onOpenChange={(next) => {
                    setDeactivating(next)
                    if (!next) setProblem(null)
                }}
                question={<Question ask={LABELS.users.deactivate_ask} code={user.username} />}
                confirm={{
                    label: LABELS.action.deactivate,
                    onConfirm: () => {
                        change(setUserActive(user.username, false), () => {
                            setDeactivating(false)
                        })
                    },
                    destructive: true,
                    busy: busy,
                }}
                words={DIALOG_WORDS}
            >
                {problem === null ? undefined : <RefusalLine problem={problem} />}
            </ConfirmDialog>
            {resetting && (
                <ResetPassword
                    username={user.username}
                    onDone={() => {
                        setResetting(false)
                    }}
                />
            )}
        </>
    )
}

/** What the dialog reads first. The role is a word, and an email and a sign-in are said where they exist. */
function AccountFacts({ user }: { user: UserOut }) {
    return (
        <DescriptionList
            items={[
                { term: LABELS.word.role, value: <span title={ROLE_HINTS[user.role]}>{user.role}</span> },
                ...(user.email === null ? [] : [{ term: LABELS.word.email, value: user.email }]),
                {
                    term: LABELS.word.last_signed_in.label,
                    value:
                        user.last_login_at === null ? LABELS.word.never : <Instant at={user.last_login_at} />,
                },
                { term: LABELS.word.created.label, value: <Instant at={user.created_at} /> },
            ]}
        />
    )
}

/**
 * The question before a reset, holding the one value it cannot go without.
 *
 * The length is checked here so a password that was always going to be refused never leaves the
 * browser, and the server's own sentence is what is drawn when one does.
 */
function ResetPassword({ username, onDone }: { username: string; onDone: () => void }) {
    const [password, setPassword] = useState('')
    const [busy, setBusy] = useState(false)
    const [problem, setProblem] = useState<Problem | null>(null)

    const send = () => {
        if (password.length < MIN_PASSWORD_LENGTH) {
            setProblem(local(LABELS.users.password_too_short(String(MIN_PASSWORD_LENGTH))))
            return
        }
        setBusy(true)
        setProblem(null)
        void resetPassword(username, password)
            .then(
                () => {
                    toast.success(LABELS.users.password_was_reset(username))
                    onDone()
                },
                (error: unknown) => {
                    setProblem(refusalOf(error))
                },
            )
            .finally(() => {
                setBusy(false)
            })
    }

    return (
        <ConfirmDialog
            open
            onOpenChange={(next) => {
                if (!next) onDone()
            }}
            question={<Question ask={LABELS.users.reset_ask} code={username} />}
            detail={LABELS.users.reset_password_note}
            confirm={{
                label: LABELS.action.reset,
                onConfirm: send,
                destructive: true,
                why: password === '' ? LABELS.users.reset_needs_password : undefined,
                busy: busy,
            }}
            words={DIALOG_WORDS}
        >
            <Field id="reset-password" label={LABELS.users.new_password}>
                <Input
                    id="reset-password"
                    type="password"
                    value={password}
                    autoComplete="new-password"
                    onChange={(event) => {
                        setPassword(event.target.value)
                    }}
                />
            </Field>
            {problem !== null && <RefusalLine problem={problem} />}
        </ConfirmDialog>
    )
}
