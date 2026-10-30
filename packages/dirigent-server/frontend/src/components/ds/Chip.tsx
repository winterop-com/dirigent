import type { ReactNode } from 'react'

import { ICONS, type Icon } from '@/lib/icons'
import { cn } from '@/lib/utils'

/** What a chip's word is: a plain word, a key, an absence, a good or bad fact, or an edit. */
export type ChipTone = 'neutral' | 'mono' | 'dashed' | 'good' | 'critical' | 'edit'

const TONES: Record<ChipTone, string> = {
    neutral: 'border-border text-muted-foreground',
    mono: 'border-border font-mono text-muted-foreground',
    dashed: 'border-dashed border-border-strong text-faint',
    good: 'border-good/30 bg-good/14 text-good-ink',
    critical: 'border-critical/30 bg-critical/14 text-critical-ink',
    edit: 'border-primary/50 text-primary-ink',
}

/** The chip's box, which `.kind-chip` and `.status-chip` match in `index.css`: 20px, the chip radius. */
const FACE =
    'inline-flex h-5 max-w-full min-w-0 items-center gap-1 rounded-sm border text-xs whitespace-nowrap'

/** A press target inside a chip: the chip's own radius, and the focus ring every control wears. */
const TARGET = 'rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring'

type Removal =
    | { onRemove?: undefined; removeLabel?: undefined }
    | { onRemove: () => void; removeLabel: string }

/**
 * One word on a chip: the shape every hand-typed word chip and every word `Badge` becomes.
 *
 * Text unless it is given `onSelect`, which makes the word a button; `onRemove` adds an X with
 * its own focus ring and its own name. A long word truncates, and `title` carries the whole.
 */
export function Chip({
    tone = 'neutral',
    children,
    title,
    icon: Glyph,
    onSelect,
    selectLabel,
    onRemove,
    removeLabel,
    className,
}: {
    tone?: ChipTone
    children: ReactNode
    /** The whole word, for a chip whose word may truncate. */
    title?: string
    icon?: Icon
    onSelect?: () => void
    /** What pressing the chip does, for the pointer and for a screen reader. */
    selectLabel?: string
    className?: string
} & Removal) {
    const word = (
        <>
            {Glyph !== undefined && <Glyph className="size-3 shrink-0" aria-hidden />}
            <span className="min-w-0 truncate">{children}</span>
        </>
    )
    const remove =
        onRemove === undefined ? null : (
            <button
                type="button"
                aria-label={removeLabel}
                title={removeLabel}
                className={cn(
                    TARGET,
                    'mr-0.5 inline-flex size-4 shrink-0 items-center justify-center text-faint hover:text-foreground',
                )}
                onClick={(event) => {
                    event.stopPropagation()
                    onRemove()
                }}
            >
                <ICONS.clear className="size-3" aria-hidden />
            </button>
        )
    if (onSelect === undefined) {
        return (
            <span
                className={cn(FACE, TONES[tone], 'pl-1.5', remove === null && 'pr-1.5', className)}
                title={title}
            >
                {word}
                {remove}
            </span>
        )
    }
    return (
        <span className={cn(FACE, TONES[tone], 'hover:border-foreground/40', className)}>
            <button
                type="button"
                title={selectLabel ?? title}
                aria-label={selectLabel}
                className={cn(
                    TARGET,
                    'inline-flex h-full min-w-0 cursor-pointer items-center gap-1 pl-1.5 hover:text-foreground',
                    remove === null ? 'pr-1.5' : 'pr-0.5',
                )}
                onClick={(event) => {
                    event.stopPropagation()
                    onSelect()
                }}
            >
                {word}
            </button>
            {remove}
        </span>
    )
}
