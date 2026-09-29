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
import { MIN_PASSWORD_LENGTH, resetPassword } from '@/lib/users'

/**
 * Set an account's password without presenting the old one.
 *
 * THE SERVER'S MINIMUM IS THE ONE THAT COUNTS. The length is checked here so a password that
 * was always going to be refused never leaves the browser, and the server's own sentence is
 * what is rendered when one does.
 */
export function ResetPassword({
    open,
    onOpenChange,
    username,
    onDone,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    /** The account whose password this sets. */
    username: string
    /** Called once the password was really set. */
    onDone: () => void
}) {
    const [password, setPassword] = useState('')
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const close = (next: boolean) => {
        if (!next) {
            setPassword('')
            setProblem(null)
        }
        onOpenChange(next)
    }

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
                    setPassword('')
                    onDone()
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
        <Dialog open={open} onOpenChange={close}>
            <DialogContent className="sm:max-w-md" showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>{LABELS.users.reset_password}</DialogTitle>
                    <DialogDescription>{LABELS.users.reset_password_hint(username)}</DialogDescription>
                </DialogHeader>

                <div className="space-y-2">
                    <Label htmlFor="reset-password">{LABELS.users.new_password}</Label>
                    <Input
                        id="reset-password"
                        type="password"
                        value={password}
                        autoComplete="new-password"
                        onChange={(event) => {
                            setPassword(event.target.value)
                        }}
                    />
                </div>

                {problem !== null && <Refusal problem={problem} />}

                <DialogFooter>
                    <DialogClose render={<Button variant="ghost" />}>{LABELS.action.cancel}</DialogClose>
                    <Button disabled={busy || password === ''} onClick={send}>
                        {LABELS.action.reset}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
