import { TagChip } from '@/components/TagChip'
import { filterWords } from '@/lib/design-system'
import { LABELS } from '@/lib/labels'
import { FilterChip, saidOptions } from '@winterop-com/sokkel-ui/FilterChip'

/**
 * The one tag filter, which every listing that has one wears.
 *
 * SEVERAL TAGS NARROW. `tag` repeats on the wire and repeating it means and, so this is a set
 * and not a choice: the menu ticks what is chosen and stays open, and the chip spells the chosen
 * tags in mono, the way a tag is spelled everywhere else.
 *
 * THE MENU IS EVERY TAG THE INSTANCE WEARS, not the tags on the rows that came back: choosing
 * one narrows the listing on the server, so a menu built from the answer would drop the tag
 * somebody adds next.
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
    const tags = [...offered, ...chosen.filter((tag) => !offered.includes(tag))]
    const options = tags.map((tag) => ({ value: tag, label: tag, row: <TagChip tag={tag} /> }))
    const said = saidOptions(options, chosen, LABELS.shell.more_chosen)
    return (
        <FilterChip
            facet={LABELS.shell.tag_filter}
            multiple
            options={options}
            selected={chosen}
            onSelectedChange={onChange}
            value={said === undefined ? undefined : <span className="font-mono">{said}</span>}
            words={filterWords()}
        />
    )
}
