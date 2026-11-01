import type { ReactNode } from 'react'

import { TextLink } from '@/components/ds/TextLink'
import { cn } from '@/lib/utils'

/** `section` heads a part of a screen; `group` heads a run of rows inside one. */
export type SectionTier = 'section' | 'group'

const TIERS: Record<SectionTier, string> = {
    section: 'text-title font-semibold',
    group: 'text-xs font-medium tracking-wide text-faint uppercase',
}

/**
 * A heading inside a screen, in one of two tiers and no third.
 *
 * `section` is sentence case at body size; `group` is the faint uppercase label over a run of
 * rows. `aside` sits opposite on the same baseline -- a count, a chip, a control -- and `link`
 * is a way to everything the section samples.
 */
export function SectionHeading({
    tier = 'section',
    children,
    aside,
    link,
    id,
    className,
}: {
    tier?: SectionTier
    children: ReactNode
    aside?: ReactNode
    link?: { to: string; label: string }
    id?: string
    className?: string
}) {
    const Tag = tier === 'section' ? 'h2' : 'h3'
    return (
        <div className={cn('flex min-w-0 items-baseline justify-between gap-3', className)}>
            <Tag
                id={id}
                className={cn('min-w-0 truncate', TIERS[tier])}
                title={typeof children === 'string' ? children : undefined}
            >
                {children}
            </Tag>
            {(aside !== undefined || link !== undefined) && (
                <div className="flex shrink-0 items-baseline gap-3 text-sm text-muted-foreground">
                    {aside}
                    {link !== undefined && (
                        <TextLink variant="aside" to={link.to}>
                            {link.label}
                        </TextLink>
                    )}
                </div>
            )}
        </div>
    )
}
