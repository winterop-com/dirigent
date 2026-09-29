import { useState } from 'react'

import { Refusal } from '@/components/Refusal'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { type Problem } from '@/lib/api'
import { LABELS } from '@/lib/labels'
import { local, refusalOf } from '@/lib/refusal'
import type { UserRole } from '@/lib/auth'
import { createUser, MIN_PASSWORD_LENGTH, ROLE_HINTS, USER_ROLES } from '@/lib/users'

/** Nothing typed yet. A new account is a viewer until somebody says otherwise. */
const BLANK = { username: '', password: '', name: '', email: '', role: 'viewer' as UserRole }

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

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-md" showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>{LABELS.users.new_account}</DialogTitle>
                    <DialogDescription>{LABELS.users.new_account_hint}</DialogDescription>
                </DialogHeader>

                <div className="space-y-2">
                    <Label htmlFor="new-username">{LABELS.word.username}</Label>
                    <Input
                        id="new-username"
                        value={form.username}
                        autoComplete="off"
                        onChange={(event) => {
                            setForm((current) => ({ ...current, username: event.target.value }))
                        }}
                    />
                </div>

                <div className="space-y-2">
                    <Label htmlFor="new-name">{LABELS.word.name.label}</Label>
                    <Input
                        id="new-name"
                        value={form.name}
                        autoComplete="off"
                        placeholder={LABELS.users.optional}
                        onChange={(event) => {
                            setForm((current) => ({ ...current, name: event.target.value }))
                        }}
                    />
                </div>

                <div className="space-y-2">
                    <Label htmlFor="new-email">{LABELS.word.email}</Label>
                    <Input
                        id="new-email"
                        value={form.email}
                        autoComplete="off"
                        placeholder={LABELS.users.optional}
                        onChange={(event) => {
                            setForm((current) => ({ ...current, email: event.target.value }))
                        }}
                    />
                </div>

                <div className="space-y-2">
                    <Label htmlFor="new-password">{LABELS.word.password}</Label>
                    <Input
                        id="new-password"
                        type="password"
                        value={form.password}
                        autoComplete="new-password"
                        onChange={(event) => {
                            setForm((current) => ({ ...current, password: event.target.value }))
                        }}
                    />
                </div>

                <fieldset className="space-y-2">
                    <legend className="text-sm font-medium">{LABELS.word.role}</legend>
                    {USER_ROLES.map((role) => (
                        <label key={role} className="flex items-start gap-2 text-sm">
                            <input
                                type="radio"
                                name="new-role"
                                className="mt-1 accent-primary"
                                checked={form.role === role}
                                onChange={() => {
                                    setForm((current) => ({ ...current, role }))
                                }}
                            />
                            <span>
                                {role}
                                <span className="block text-xs text-muted-foreground">
                                    {ROLE_HINTS[role]}
                                </span>
                            </span>
                        </label>
                    ))}
                </fieldset>

                {problem !== null && <Refusal problem={problem} />}

                <DialogFooter>
                    <DialogClose render={<Button variant="ghost" />}>{LABELS.action.cancel}</DialogClose>
                    <Button
                        disabled={busy || form.username.trim() === '' || form.password === ''}
                        onClick={send}
                    >
                        {LABELS.action.create.verb}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
