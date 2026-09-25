import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

/** What a search box says while it is empty, wherever one is drawn. */
export const SEARCH_PLACEHOLDER = 'Search'

/**
 * The box that narrows what is on the screen.
 *
 * THE PLACEHOLDER NAMES NOTHING. A box under a heading is a box searching what the heading
 * names, so a placeholder naming it again puts the noun on the screen twice. The noun lives on
 * `label` instead, which is the accessible name, read without the heading beside it and free to
 * say what a match is made over.
 */
export function SearchField({
    value,
    label,
    onChange,
    className,
}: {
    value: string
    /** What the box is called, and what it matches on, for whoever is not seeing the screen. */
    label: string
    onChange: (typed: string) => void
    className?: string
}) {
    return (
        <Input
            className={cn('w-56', className)}
            value={value}
            aria-label={label}
            placeholder={SEARCH_PLACEHOLDER}
            onChange={(event) => {
                onChange(event.target.value)
            }}
        />
    )
}
