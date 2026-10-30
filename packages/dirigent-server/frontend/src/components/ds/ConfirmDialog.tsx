import type { ReactNode } from 'react'

import { DialogShell } from '@/components/ds/DialogShell'
import type { Problem } from '@/lib/api'
import { refusalLine } from '@/lib/refusal'

/**
 * The question before a verb that takes something away: revoke, deactivate, delete, rotate.
 *
 * The title is the question and names the thing, its code in mono and nowhere else, and the
 * confirm is the verb in the critical fill. There is no body unless `note` says what changes the
 * answer. `why` shuts the confirm and is what its title says. A refusal is one line in the body,
 * and the dialog stays open on it.
 */
export function ConfirmDialog({
    open,
    onOpenChange,
    ask,
    code,
    note,
    why,
    verb,
    busy = false,
    busyVerb,
    problem = null,
    onConfirm,
    children,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    /** The question around the code: "Delete " and "?". */
    ask: { before: string; after: string }
    /** The code of the thing the verb is about, drawn in mono. */
    code: string
    /** The one line that changes the answer, where there is one. */
    note?: ReactNode
    /** Why the verb cannot be taken. It stays drawn, shut, and says this on hover. */
    why?: string
    verb: string
    busy?: boolean
    busyVerb?: string
    problem?: Problem | null
    onConfirm: () => void
    /** The one field a verb cannot go without, where it has one. */
    children?: ReactNode
}) {
    const hasBody = note !== undefined || problem !== null || children !== undefined
    return (
        <DialogShell
            open={open}
            onOpenChange={onOpenChange}
            width="sm"
            title={
                <>
                    {ask.before}
                    <span className="font-mono break-all">{code}</span>
                    {ask.after}
                </>
            }
            confirm={{ label: verb, busy, busyLabel: busyVerb, destructive: true, why, onConfirm }}
        >
            {hasBody ? (
                <>
                    {note !== undefined && <p className="text-sm text-muted-foreground">{note}</p>}
                    {children}
                    {problem !== null && (
                        <p className="text-sm text-critical-ink" role="alert">
                            {refusalLine(problem)}
                        </p>
                    )}
                </>
            ) : undefined}
        </DialogShell>
    )
}
