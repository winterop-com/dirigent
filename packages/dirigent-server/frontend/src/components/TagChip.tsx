import { cn } from '@/lib/utils'

/**
 * One tag, drawn the one way this app draws a tag.
 *
 * NEUTRAL AND MONO, AND NOT A KIND. A tag is a word somebody chose, not a value out of an enum
 * this app knows the meaning of, so it takes no hue: amber means action and the kind families
 * mean what a thing is, and a vocabulary an instance invented is allowed to mean neither. Mono
 * because it is a key, spelled exactly, like every other key on screen.
 *
 * A CHIP GIVEN `onSelect` IS A BUTTON, AND ONE WITHOUT IT IS TEXT. Nothing wears interactive
 * chrome unless it does something, so only the chip that narrows a listing lights under the
 * pointer and answers a keyboard.
 */
export function TagChip({
    tag,
    className,
    onSelect,
    label,
}: {
    tag: string
    className?: string
    /** What clicking this tag asks for, which is always "narrow to this". */
    onSelect?: () => void
    /** What clicking it is called, for the pointer and for a screen reader. */
    label?: string
}) {
    const face = cn('border-border text-muted-foreground rounded-sm border px-1.5 font-mono text-xs', className)
    if (onSelect === undefined) return <span className={face}>{tag}</span>
    return (
        <button
            type="button"
            className={cn(face, 'hover:border-foreground/40 hover:text-foreground cursor-pointer')}
            aria-label={label ?? `Filter by ${tag}`}
            title={label ?? `Filter by ${tag}`}
            onClick={(event) => {
                event.stopPropagation()
                onSelect()
            }}
        >
            {tag}
        </button>
    )
}
