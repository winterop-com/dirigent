import { Check, Copy } from 'lucide-react'
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
import { refusalOf } from '@/lib/refusal'
import { createToken, createTokenFor, type IssuedTokenOut } from '@/lib/users'

/** What the dialog says about the one showing of the secret. */
export const TOKEN_ONCE = 'This is the only time this token will be shown.'

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
    const [copied, setCopied] = useState(false)

    const close = (next: boolean) => {
        if (!next) {
            setName('')
            setIssued(null)
            setProblem(null)
            setCopied(false)
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
            <DialogContent className="sm:max-w-lg" showCloseButton={false}>
                <DialogHeader>
                    <DialogTitle>New token</DialogTitle>
                    <DialogDescription>
                        {username === undefined
                            ? 'It holds whatever this account holds.'
                            : `It holds whatever ${username} holds.`}
                    </DialogDescription>
                </DialogHeader>

                {issued === null ? (
                    <div className="space-y-2">
                        <Label htmlFor="new-token-name">Name</Label>
                        <Input
                            id="new-token-name"
                            value={name}
                            autoComplete="off"
                            placeholder="ci-deploy"
                            onChange={(event) => {
                                setName(event.target.value)
                            }}
                        />
                        <p className="text-xs text-muted-foreground">
                            Lower case, digits and single hyphens. It is what the token is revoked by.
                        </p>
                    </div>
                ) : (
                    <div className="space-y-2 rounded-lg border border-border bg-secondary/40 p-3">
                        <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                            <span className="text-sm font-medium">{issued.name}</span>
                            <span className="font-mono text-xs text-muted-foreground">{issued.username}</span>
                        </p>
                        <p className="text-xs text-warning">{TOKEN_ONCE}</p>
                        <div className="flex items-center gap-2">
                            <code className="flex-1 overflow-x-auto rounded-md border border-border bg-background p-2 font-mono text-xs break-all">
                                {issued.token}
                            </code>
                            <Button
                                variant="outline"
                                size="sm"
                                aria-label="Copy the token"
                                onClick={() => {
                                    void navigator.clipboard.writeText(issued.token).then(
                                        () => {
                                            setCopied(true)
                                        },
                                        () => {
                                            setCopied(false)
                                        },
                                    )
                                }}
                            >
                                {copied ? <Check aria-hidden /> : <Copy aria-hidden />}
                                {copied ? 'Copied' : 'Copy'}
                            </Button>
                        </div>
                    </div>
                )}

                {problem !== null && <Refusal problem={problem} />}

                <DialogFooter>
                    <DialogClose render={<Button variant={issued === null ? 'ghost' : 'default'} />}>
                        {issued === null ? 'Cancel' : 'Done'}
                    </DialogClose>
                    {issued === null && (
                        <Button disabled={busy || name.trim() === ''} onClick={send}>
                            Create
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
