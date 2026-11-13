import { useState } from 'react'

import { Refusal } from '@/components/Refusal'
import { RoleSelect } from '@/components/admin/RoleSelect'
import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { SecretField } from '@winterop-com/sokkel-ui/SecretField'
import { TextField } from '@winterop-com/sokkel-ui/TextField'
import { type Problem } from '@/lib/api'
import { DIALOG_WORDS, FIELD_WORDS, SECRET_FIELD_WORDS } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { local, refusalOf } from '@/lib/refusal'
import type { UserRole } from '@/lib/auth'
import { createUser, MIN_PASSWORD_LENGTH } from '@/lib/users'

/** Nothing typed yet. A new account is a viewer until somebody says otherwise. */
const BLANK = {
    username: '',
    password: '',
    name: '',
    email: '',
    role: 'viewer' as UserRole,
}

/** No box left yet: what the dialog opens on. */
const NONE_LEFT = { username: false, password: false }

/**
 * Make a local account.
 *
 * THE ROLE RADIO PRE-SELECTS VIEWER, AND A ROLE IS ALWAYS SENT. The API has no default and
 * refuses a request that names none, so the dialog opens on the least of the three.
 *
 * THE PASSWORD LENGTH IS CHECKED HERE AND ON THE SERVER. The server's answer is authoritative
 * and is rendered when it comes; checking first is what keeps a password out of a request that
 * was always going to be refused.
 */
export function CreateUser({
    open,
    onOpenChange,
    onCreated,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    /** Called when an account was really made, so the listing behind can read itself again. */
    onCreated: () => void
}) {
    const [form, setForm] = useState(BLANK)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)
    // Which boxes have been left once, so a required one says so only after somebody was there.
    const [left, setLeft] = useState(NONE_LEFT)

    const send = () => {
        if (form.password.length < MIN_PASSWORD_LENGTH) {
            setProblem(local(LABELS.users.password_too_short(String(MIN_PASSWORD_LENGTH))))
            return
        }
        setBusy(true)
        setProblem(null)
        void createUser({
            username: form.username.trim(),
            password: form.password,
            name: form.name.trim() === '' ? null : form.name.trim(),
            email: form.email.trim() === '' ? null : form.email.trim(),
            role: form.role,
        })
            .then(
                () => {
                    setForm(BLANK)
                    setLeft(NONE_LEFT)
                    onCreated()
                    onOpenChange(false)
                },
                (error: unknown) => {
                    setProblem(refusalOf(error))
                },
            )
            .finally(() => {
                setBusy(false)
            })
    }

    const shut =
        form.username.trim() === ''
            ? LABELS.users.account_needs_username
            : form.password === ''
              ? LABELS.users.account_needs_password
              : undefined
    const usernameIssue =
        left.username && form.username.trim() === '' ? LABELS.users.account_needs_username : null
    const passwordIssue = left.password && form.password === '' ? LABELS.users.account_needs_password : null

    return (
        <DialogShell
            words={DIALOG_WORDS}
            open={open}
            onOpenChange={(next) => {
                if (!next) setLeft(NONE_LEFT)
                onOpenChange(next)
            }}
            title={LABELS.users.new_account}
            confirm={{
                label: LABELS.action.create.verb,
                busy,
                busyLabel: LABELS.action.create.busy,
                why: shut,
                onConfirm: send,
            }}
        >
            <TextField
                id="new-username"
                label={LABELS.word.username}
                required
                requiredMark="word"
                words={FIELD_WORDS}
                error={usernameIssue}
                mono
                value={form.username}
                autoComplete="off"
                onChange={(username) => {
                    setForm((current) => ({ ...current, username }))
                }}
                onBlur={() => {
                    setLeft((was) => ({ ...was, username: true }))
                }}
            />

            <TextField
                id="new-name"
                label={LABELS.word.name.label}
                value={form.name}
                autoComplete="off"
                onChange={(name) => {
                    setForm((current) => ({ ...current, name }))
                }}
            />

            <TextField
                id="new-email"
                label={LABELS.word.email}
                value={form.email}
                autoComplete="off"
                onChange={(email) => {
                    setForm((current) => ({ ...current, email }))
                }}
            />

            <SecretField
                id="new-password"
                label={LABELS.word.password}
                required
                requiredMark="word"
                words={SECRET_FIELD_WORDS}
                error={passwordIssue}
                mono={false}
                value={form.password === '' ? undefined : form.password}
                onChange={(password) => {
                    setForm((current) => ({ ...current, password: password ?? '' }))
                }}
                onBlur={() => {
                    setLeft((was) => ({ ...was, password: true }))
                }}
            />

            <RoleSelect
                id="new-role"
                value={form.role}
                onChange={(role) => {
                    setForm((current) => ({ ...current, role }))
                }}
            />

            {problem !== null && <Refusal problem={problem} />}
        </DialogShell>
    )
}
