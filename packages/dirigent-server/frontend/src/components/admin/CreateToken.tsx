import { useState } from 'react'

import { InlineCode } from '@winterop-com/sokkel-ui/InlineCode'
import { Refusal } from '@/components/Refusal'
import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { describedBy, Field } from '@winterop-com/sokkel-ui/Field'
import { Input } from '@winterop-com/sokkel-ui/primitives/input'
import { SecretReveal } from '@winterop-com/sokkel-ui/SecretReveal'
import { type Problem } from '@/lib/api'
import { DIALOG_WORDS, FIELD_WORDS, secretWords } from '@/lib/design-system'
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
    // Whether the name box has been left once, so it says it is empty only after somebody was there.
    const [left, setLeft] = useState(false)

    const close = (next: boolean) => {
        if (!next) {
            setName('')
            setIssued(null)
            setProblem(null)
            setLeft(false)
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

    const nameIssue = left && name.trim() === '' ? LABELS.users.token_needs_name : null

    return (
        <DialogShell
            words={DIALOG_WORDS}
            open={open}
            onOpenChange={close}
            title={LABELS.users.new_token}
            description={
                username === undefined
                    ? LABELS.users.token_scope_self
                    : LABELS.users.token_scope_for(username)
            }
            confirm={
                issued === null
                    ? {
                          label: LABELS.action.create.verb,
                          busy,
                          busyLabel: LABELS.action.create.busy,
                          why: name.trim() === '' ? LABELS.users.token_needs_name : undefined,
                          onConfirm: send,
                      }
                    : undefined
            }
        >
            {issued === null ? (
                <Field
                    id="new-token-name"
                    label={LABELS.word.name.label}
                    required
                    requiredMark="word"
                    words={FIELD_WORDS}
                    help={LABELS.users.token_name_hint}
                    error={nameIssue}
                >
                    <Input
                        id="new-token-name"
                        aria-required
                        aria-invalid={nameIssue !== null || undefined}
                        aria-describedby={describedBy('new-token-name', {
                            help: LABELS.users.token_name_hint,
                        })}
                        value={name}
                        autoComplete="off"
                        placeholder={LABELS.users.token_name_placeholder}
                        onChange={(event) => {
                            setName(event.target.value)
                        }}
                        onBlur={() => {
                            setLeft(true)
                        }}
                    />
                </Field>
            ) : (
                <div className="space-y-2">
                    <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <span className="text-sm font-medium">{issued.name}</span>
                        <InlineCode value={issued.username} tone="muted" bare size="xs" />
                    </p>
                    <SecretReveal
                        value={issued.token}
                        words={secretWords(LABELS.users.token_noun)}
                        autoFocus
                    />
                </div>
            )}

            {problem !== null && <Refusal problem={problem} />}
        </DialogShell>
    )
}
