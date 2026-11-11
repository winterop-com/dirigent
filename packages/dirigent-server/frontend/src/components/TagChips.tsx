import { TagChip } from '@/components/TagChip'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@winterop-com/sokkel-ui/primitives/dropdown-menu'
import { foldTags } from '@/lib/tag-fold'
import { counted, LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'
import { Chip } from '@winterop-com/sokkel-ui/Chip'
import { useTableCell } from '@winterop-com/sokkel-ui/DataTable'

/**
 * Every tag a row wears, folded to the room its column has.
 *
 * THE FOLD IS COMPUTED, NOT GUESSED. `lib/tag-fold` fits the words into `room`, the width in
 * pixels of the column the chips stand in, counting the `+N` as the chip it is, so what is drawn
 * is what fits on one line and never one chip past it. Without a room every chip up to the cap
 * is drawn and wraps. On a stacked card the room is ignored and the chips wrap across the card's
 * width; outside a `DataTable` the chips are never stacked.
 */
export function TagChips({
    tags,
    room = 0,
    onSelect,
}: {
    tags: readonly string[]
    /** The width of the column the chips stand in, in pixels; 0 for no bound. */
    room?: number
    /** What clicking a tag asks for, which is always "narrow to this". */
    onSelect?: (tag: string) => void
}) {
    const { stacked } = useTableCell()
    if (tags.length === 0) return null
    const bound = stacked ? 0 : room
    const fold = foldTags(tags, bound, 1)
    return (
        <span
            className={cn(
                'flex items-center gap-1',
                stacked ? 'flex-wrap' : bound > 0 ? 'flex-nowrap' : 'w-max max-w-[25cqi] flex-wrap',
            )}
        >
            {fold.shown.map((tag) => (
                <TagChip
                    key={tag}
                    tag={tag}
                    onSelect={
                        onSelect === undefined
                            ? undefined
                            : () => {
                                  onSelect(tag)
                              }
                    }
                />
            ))}
            {fold.folded.length > 0 && <FoldedTags tags={fold.folded} onSelect={onSelect} />}
        </span>
    )
}

/** What the rest of the tags say for themselves, and the menu that filters by one of them. */
function FoldedTags({ tags, onSelect }: { tags: readonly string[]; onSelect?: (tag: string) => void }) {
    const label = counted(tags.length, LABELS.shell.folded_tags)(String(tags.length), tags.join(', '))
    const chip = `+${String(tags.length)}`
    const face =
        'inline-flex h-5 items-center rounded-chip bg-faint/15 px-1.5 font-mono text-badge text-muted-foreground'
    if (onSelect === undefined)
        return (
            <Chip mono title={label}>
                {chip}
            </Chip>
        )
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <button
                        type="button"
                        className={cn(
                            face,
                            'cursor-pointer hover:text-foreground hover:underline hover:underline-offset-2',
                        )}
                        aria-label={label}
                        title={label}
                        onClick={(event) => {
                            event.stopPropagation()
                        }}
                    >
                        {chip}
                    </button>
                }
            />
            <DropdownMenuContent align="start" className="min-w-40">
                {tags.map((tag) => (
                    <DropdownMenuItem
                        key={tag}
                        onClick={(event) => {
                            event.stopPropagation()
                            onSelect(tag)
                        }}
                    >
                        <TagChip tag={tag} />
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
