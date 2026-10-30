import type { ReactNode } from 'react'

import { headingOf, oneLine, type Addressable } from '@/lib/identity'
import { cn } from '@/lib/utils'

/**
 * Where a heading stands: a listing's lead cell with the code under the title, a row with the
 * code beside it, or the head of a panel.
 */
export type EntityHeadingVariant = 'row-stacked' | 'row-inline' | 'panel'

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
    className,
}: {
    thing: Addressable
    variant?: EntityHeadingVariant
    chips?: ReactNode
    description?: string | null
    /** A kind's mark, drawn before the title. */
    glyph?: ReactNode
    className?: string
}) {
    const heading = headingOf(thing)
    const panel = variant === 'panel'
    const Title = panel ? 'h2' : 'span'
    const title = (
        <Title
            className={cn(
                'min-w-0 text-sm font-medium',
                panel ? 'break-words' : 'truncate',
                !heading.named && 'font-mono',
            )}
            title={panel ? undefined : heading.title}
        >
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
        <div className={cn('flex min-w-0 flex-col', panel ? 'gap-1' : 'gap-0.5', className)}>
            <div
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
            </div>
            {variant !== 'row-inline' && code}
            {line !== null && (
                <p
                    className={cn('min-w-0 text-xs text-faint', panel ? 'line-clamp-2' : 'truncate')}
                    title={panel ? undefined : line}
                >
                    {line}
                </p>
            )}
        </div>
    )
}
