import { ChevronDown } from 'lucide-react'

import { TagChip } from '@/components/TagChip'
import { Button } from '@winterop-com/sokkel-ui/primitives/button'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuTrigger,
} from '@winterop-com/sokkel-ui/primitives/dropdown-menu'
import { chipWords } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { Chip } from '@winterop-com/sokkel-ui/Chip'

/**
 * The one tag filter, which both listings that have one wear.
 *
 * SEVERAL TAGS NARROW. `tag` repeats on the wire and repeating it means and, so this is a set
 * and not a choice: the menu checks what is chosen, and every chosen tag stands beside it as a
 * chip that removes itself. A control that could hold only one would ask a question the API
 * does not, and "the nightly acme imports" is an intersection.
 *
 * THE MENU IS EVERY TAG THE INSTANCE WEARS, not the tags on the rows that came back: choosing
 * one narrows the listing on the server, so a menu built from the answer would drop the tag
 * somebody adds next.
 *
 * THE TRIGGER STATES NO COUNT. The chips beside it are the chosen tags, spelled out, so a
 * number on the trigger would say the same fact a second time.
 */
export function TagFilter({
    chosen,
    offered,
    onChange,
}: {
    chosen: readonly string[]
    offered: readonly string[]
    onChange: (tags: string[]) => void
}) {
    const toggle = (tag: string) => {
        onChange(chosen.includes(tag) ? chosen.filter((one) => one !== tag) : [...chosen, tag])
    }
    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button variant="outline" size="sm" aria-label={LABELS.shell.tag_filter.label}>
                            {chosen.length === 0
                                ? LABELS.shell.tag_filter.any
                                : LABELS.shell.tag_filter.chosen}
                            <ChevronDown aria-hidden />
                        </Button>
                    }
                />
                <DropdownMenuContent align="start" className="min-w-56">
                    {offered.map((tag) => (
                        <DropdownMenuCheckboxItem
                            key={tag}
                            checked={chosen.includes(tag)}
                            className="whitespace-nowrap"
                            onCheckedChange={() => {
                                toggle(tag)
                            }}
                        >
                            <TagChip tag={tag} />
                        </DropdownMenuCheckboxItem>
                    ))}
                </DropdownMenuContent>
            </DropdownMenu>
            {chosen.map((tag) => (
                <Chip
                    key={tag}
                    mono
                    words={chipWords(LABELS.shell.stop_filtering_by_tag(tag))}
                    onRemove={() => {
                        onChange(chosen.filter((one) => one !== tag))
                    }}
                >
                    {tag}
                </Chip>
            ))}
        </>
    )
}
