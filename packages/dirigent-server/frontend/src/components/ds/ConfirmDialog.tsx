import type { ReactNode } from 'react'

import { DialogShell } from '@/components/ds/DialogShell'
import { Refusal } from '@/components/Refusal'
import type { Problem } from '@/lib/api'

/**
 * The question before a verb that takes something away: revoke, deactivate, delete, rotate.
 *
 * The title is the verb and the thing, the body names the thing in mono and says what is lost,
 * and the confirm is the verb again in the critical fill. A refusal is drawn in the body and
 * the dialog stays open on it.
 */
export function ConfirmDialog({
    open,
    onOpenChange,
    title,
    code,
    consequence,
    verb,
    busy = false,
    busyVerb,
    problem = null,
    onConfirm,
}: {
    open: boolean
    onOpenChange: (open: boolean) => void
    /** The verb and the thing, as a heading: "Revoke token". */
    title: string
    /** The code of the thing the verb is about, drawn in mono. */
    code: string
    /** What pressing the verb costs, as a sentence. */
    consequence: ReactNode
    verb: string
    busy?: boolean
    busyVerb?: string
    problem?: Problem | null
    onConfirm: () => void
}) {
    return (
        <DialogShell
            open={open}
            onOpenChange={onOpenChange}
            width="sm"
            title={title}
            confirm={{ label: verb, busy, busyLabel: busyVerb, destructive: true, onConfirm }}
        >
            <p className="font-mono text-sm break-all">{code}</p>
            <p className="text-sm text-muted-foreground">{consequence}</p>
            {problem !== null && <Refusal problem={problem} />}
        </DialogShell>
    )
}
