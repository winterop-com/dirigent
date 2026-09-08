import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Kbd, KbdGroup } from '@/components/ui/kbd'
import { applePlatform, shortcuts } from '@/lib/shortcuts'

export const SHORTCUTS_TITLE = 'Keyboard shortcuts'

/**
 * The list of every key this app answers.
 *
 * A shortcut nobody has been told about is a shortcut nobody has, so the list is reachable by
 * the `?` key and offered as a palette row as well.
 */
export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
    const rows = shortcuts(applePlatform(navigator.userAgent))
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle>{SHORTCUTS_TITLE}</DialogTitle>
                </DialogHeader>
                <dl className="grid gap-2">
                    {rows.map((row) => (
                        <div key={row.id} className="flex items-center justify-between gap-4">
                            <dt className="text-sm">{row.action}</dt>
                            <dd>
                                <KbdGroup>
                                    {row.keys.map((key) => (
                                        <Kbd key={key}>{key}</Kbd>
                                    ))}
                                </KbdGroup>
                            </dd>
                        </div>
                    ))}
                </dl>
            </DialogContent>
        </Dialog>
    )
}
