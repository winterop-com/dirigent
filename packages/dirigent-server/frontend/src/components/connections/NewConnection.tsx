import { ConnectionFields } from '@/components/connections/ConnectionFields'
import { DialogShell } from '@winterop-com/sokkel-ui/DialogShell'
import { useConnectionDraft } from '@/hooks/use-connection-draft'
import { type ConnectionOut, type SurfaceEntry } from '@/lib/connections'
import { DIALOG_WORDS } from '@/lib/library-words'
import { LABELS } from '@/lib/labels'

/**
 * Mint one connection of a kind this instance has installed.
 *
 * THE DIALOG IS THE ASKING AND NOTHING ELSE. What a draft holds, what it sends and why Create is
 * shut are `hooks/use-connection-draft`'s, and the boxes are `ConnectionFields` -- because the
 * same credential is minted from the row of an apply's carried offer, and a second copy of this
 * form there would be a second set of rules about secrets and about what a blank box means.
 */
export function NewConnection({
    open,
    kinds,
    startKind = '',
    onOpenChange,
    onCreated,
}: {
    open: boolean
    /** What this instance has installed, from the catalog the screen read. */
    kinds: SurfaceEntry[]
    /** The kind the dialog opens on, for a link that already knows which one is wanted. */
    startKind?: string
    onOpenChange: (open: boolean) => void
    /** Called with what was minted, so the listing behind reads itself again. */
    onCreated: (row: ConnectionOut) => void
}) {
    const form = useConnectionDraft(kinds, '', startKind)

    return (
        <DialogShell
            words={DIALOG_WORDS}
            open={open}
            onOpenChange={onOpenChange}
            width="lg"
            title={LABELS.connections.new}
            description={LABELS.connections.sealed}
            confirm={{
                label: LABELS.action.create.verb,
                busy: form.busy,
                busyLabel: LABELS.action.create.busy,
                why: form.shut,
                onConfirm: () => {
                    form.create((row) => {
                        onCreated(row)
                        onOpenChange(false)
                    })
                },
            }}
        >
            <ConnectionFields form={form} kinds={kinds} ids="connection-new" />
        </DialogShell>
    )
}
