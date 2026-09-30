import { ConnectionFields } from '@/components/connections/ConnectionFields'
import { Refusable } from '@/components/Refusable'
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
import { useConnectionDraft } from '@/hooks/use-connection-draft'
import { type ConnectionOut, type SurfaceEntry } from '@/lib/connections'
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
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                className="flex max-h-[calc(100vh-4rem)] flex-col sm:max-w-xl"
                showCloseButton={false}
            >
                <DialogHeader>
                    <DialogTitle>{LABELS.connections.new}</DialogTitle>
                    <DialogDescription>{LABELS.connections.sealed}</DialogDescription>
                </DialogHeader>

                {/* The boxes scroll and the verbs do not: a kind with a dozen settings is
                    taller than a short screen, and Create is what somebody reaches for. */}
                <div className="-mx-1 min-h-0 flex-1 space-y-4 overflow-y-auto px-1">
                    <ConnectionFields form={form} kinds={kinds} ids="connection-new" />
                </div>

                <DialogFooter>
                    <DialogClose render={<Button variant="ghost" />}>{LABELS.action.close}</DialogClose>
                    <Refusable why={form.shut}>
                        <Button
                            disabled={form.busy || form.shut !== undefined}
                            title={form.shut}
                            onClick={() => {
                                form.create((row) => {
                                    onCreated(row)
                                    onOpenChange(false)
                                })
                            }}
                        >
                            {form.busy ? LABELS.action.create.busy : LABELS.action.create.verb}
                        </Button>
                    </Refusable>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
