import type { ReactNode } from 'react'

import { headingOf, oneLine, type Addressable } from '@/lib/identity'
import { cn } from '@/lib/utils'

/**
 * Where a heading stands: a listing's lead cell with the code under the title, a row with the
 * code beside it, the head of a panel, or inside a dialog's title, whose size it takes.
 */
export type EntityHeadingVariant = 'row-stacked' | 'row-inline' | 'panel' | 'dialog'

/**
 * How one addressable thing is headed, everywhere: the name, else the code; the code always on
 * screen in mono and never twice; chips beside the title; an optional one-line description.
 *
 * One title weight in all three variants. A row truncates every line and carries the whole
 * title on hover; a panel wraps its title and gives the description two lines.
 */
export function EntityHeading({
    thing,
    variant = 'row-stacked',
    chips,
    description,
    glyph,
    lead,
    className,
}: {
    thing: Addressable
    variant?: EntityHeadingVariant
    chips?: ReactNode
    description?: string | null
    /** A kind's mark, drawn before the title. */
    glyph?: ReactNode
    /** A word in front of the title that is not part of it: what is being done to the thing. */
    lead?: string
    className?: string
}) {
    const heading = headingOf(thing)
    const inTitle = variant === 'dialog'
    const panel = variant === 'panel' || inTitle
    const Title = variant === 'panel' ? 'h2' : 'span'
    const Box = inTitle ? 'span' : 'div'
    const title = (
        <Title
            className={cn(
                'min-w-0 font-medium',
                !inTitle && 'text-sm',
                panel ? 'break-words' : 'truncate',
                !heading.named && 'font-mono',
            )}
            title={panel ? undefined : heading.title}
        >
            {lead !== undefined && <span className="font-sans">{lead} </span>}
            {heading.title}
        </Title>
    )
    const code =
        heading.code === null ? null : (
            <span className="min-w-0 truncate font-mono text-xs text-muted-foreground" title={heading.code}>
                {heading.code}
            </span>
        )
    const line =
        description === undefined || description === null || description.trim() === ''
            ? null
            : oneLine(description)
    return (
        <Box className={cn('flex min-w-0 flex-col', panel ? 'gap-1' : 'gap-0.5', className)}>
            <Box
                className={cn(
                    'flex min-w-0 items-center gap-2',
                    variant === 'row-inline' && 'items-baseline',
                )}
            >
                {glyph !== undefined && (
                    <span className="shrink-0 self-center text-muted-foreground">{glyph}</span>
                )}
                {title}
                {variant === 'row-inline' && code}
                {chips !== undefined && <span className="flex shrink-0 items-center gap-1">{chips}</span>}
            </Box>
            {variant !== 'row-inline' && code}
            {line !== null && (
                <p
                    className={cn('min-w-0 text-xs text-faint', panel ? 'line-clamp-2' : 'truncate')}
                    title={panel ? undefined : line}
                >
                    {line}
                </p>
            )}
        </Box>
    )
}
