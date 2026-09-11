import { useListWidth } from '@/components/list/ListWidth'
import { TagChip } from '@/components/TagChip'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useNarrowTable } from '@/hooks/use-small-screen'
import { foldTags, linesFor, roomFor } from '@/lib/tag-fold'
import { cn } from '@/lib/utils'

/**
 * Every tag a listing row wears, inside the room the row's identity has left it.
 *
 * THE IDENTITY TAKES THE WIDTH. A tag is what a row is filed under and the title, the code and
 * the description are what it is, so the chips get a quarter of the table and no more, and what
 * does not fit that quarter folds rather than widening the column or wrapping under it.
 *
 * THE FOLD IS COMPUTED, NOT GUESSED. `lib/tag-fold` fits the words into the room the table
 * measured, counting the `+N` as the chip it is, so what is drawn is what fits on the line and
 * never one chip past it. A table at `WRAPS_AT` or wider is allowed the second line.
 *
 * A CARD IS NOT A COLUMN. Below `lg` a row is a card and the tags have a row of their own, so
 * there is nothing to take width from and every chip is drawn.
 */
export function TagChips({
    tags,
    onSelect,
}: {
    tags: readonly string[]
    /** What clicking a tag asks for, which is always "narrow to this". */
    onSelect?: (tag: string) => void
}) {
    const cards = useNarrowTable()
    const table = useListWidth()
    if (tags.length === 0) return null
    const fold = cards ? { shown: [...tags], folded: [] } : foldTags(tags, roomFor(table), linesFor(table))
    return (
        <span className={cn('flex flex-wrap items-center gap-1', !cards && 'w-max max-w-[25cqi]')}>
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
    const label = `${String(tags.length)} more tags: ${tags.join(', ')}`
    const chip = `+${String(tags.length)}`
    const face = 'border-border text-muted-foreground rounded-sm border px-1.5 font-mono text-xs'
    if (onSelect === undefined)
        return (
            <span className={face} title={label}>
                {chip}
            </span>
        )
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <button
                        type="button"
                        className={cn(
                            face,
                            'cursor-pointer hover:border-foreground/40 hover:text-foreground',
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
