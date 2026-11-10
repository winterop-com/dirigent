import { useState } from 'react'

import { Code } from '@/components/ds/Code'
import { Refusal } from '@/components/Refusal'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import {
    Dialog,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from '@winterop-com/sokkel-ui/primitives/dialog'
import { Input } from '@winterop-com/sokkel-ui/primitives/input'
import { Label } from '@winterop-com/sokkel-ui/primitives/label'
import { SecretReveal } from '@winterop-com/sokkel-ui/SecretReveal'
import { type Problem } from '@/lib/api'
import { secretWords } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { refusalOf } from '@/lib/refusal'
import { createToken, createTokenFor, type IssuedTokenOut } from '@/lib/users'

/**
 * Mint a token for automation, and show the secret once.
 *
 * THE SECRET IS NOT STORED AND CANNOT BE READ AGAIN. The server hashes it and answers the
 * plaintext exactly once, so the dialog stays open on the minted token rather than closing on
 * success the way every other create does -- closing would be throwing the answer away.
 *
 * The name is an entity name: lower case, digits and single hyphens. A name that is not one is
 * refused by the server, in the server's own words.
 *
 * WITH A USERNAME IT MINTS FOR THAT ACCOUNT, and without one it mints for the caller.
 */
export function CreateToken({
    open,
    onOpenChange,
    onCreated,
    username,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    /** Called when a token was really minted, so the listing behind can read itself again. */
    onCreated: () => void
    /** Which account the token authenticates as. The caller's own where this is not given. */
    username?: string
}) {
    const [name, setName] = useState('')
    const [issued, setIssued] = useState<IssuedTokenOut | null>(null)
    const [problem, setProblem] = useState<Problem | null>(null)
    const [busy, setBusy] = useState(false)

    const close = (next: boolean) => {
        if (!next) {
            setName('')
            setIssued(null)
            setProblem(null)
        }
        onOpenChange(next)
    }

    const send = () => {
        setBusy(true)
        setProblem(null)
        const minting =
            username === undefined ? createToken(name.trim()) : createTokenFor(username, name.trim())
        void minting
            .then(
                (answer) => {
                    setIssued(answer)
                    onCreated()
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
            <DialogContent className="sm:max-w-lg" showCloseButton={issued !== null}>
                <DialogHeader>
                    <DialogTitle>{LABELS.users.new_token}</DialogTitle>
                    <DialogDescription>
                        {username === undefined
                            ? LABELS.users.token_scope_self
                            : LABELS.users.token_scope_for(username)}
                    </DialogDescription>
                </DialogHeader>

                {issued === null ? (
                    <div className="space-y-2">
                        <Label htmlFor="new-token-name">{LABELS.word.name.label}</Label>
                        <Input
                            id="new-token-name"
                            value={name}
                            autoComplete="off"
                            placeholder={LABELS.users.token_name_placeholder}
                            onChange={(event) => {
                                setName(event.target.value)
                            }}
                        />
                        <p className="text-xs text-muted-foreground">{LABELS.users.token_name_hint}</p>
                    </div>
                ) : (
                    <div className="space-y-2">
                        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <span className="text-sm font-medium">{issued.name}</span>
                            <Code value={issued.username} />
                        </p>
                        <SecretReveal
                            value={issued.token}
                            words={secretWords(LABELS.users.token_noun)}
                            autoFocus
                        />
                    </div>
                )}

                {problem !== null && <Refusal problem={problem} />}

                {issued === null && (
                    <DialogFooter>
                        <DialogClose render={<Button variant="ghost" />}>{LABELS.action.cancel}</DialogClose>
                        <Button disabled={busy || name.trim() === ''} onClick={send}>
                            {LABELS.action.create.verb}
                        </Button>
                    </DialogFooter>
                )}
            </DialogContent>
        </Dialog>
    )
}
