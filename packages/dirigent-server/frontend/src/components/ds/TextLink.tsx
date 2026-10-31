import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/** Where a link sits: in prose, as a value in a table, or out of this app. */
export type TextLinkVariant = 'inline' | 'data' | 'aside' | 'external'

const VARIANTS: Record<TextLinkVariant, string> = {
    inline: 'text-foreground underline decoration-foreground/35 underline-offset-2 hover:decoration-foreground',
    data: 'text-foreground font-mono tabular-nums hover:underline underline-offset-2',
    aside: 'text-muted-foreground hover:text-foreground hover:underline underline-offset-2',
    external:
        'inline-flex items-center gap-0.5 text-foreground underline decoration-foreground/35 underline-offset-2 hover:decoration-foreground',
}

/**
 * A link, in the one amber the app spends on a link and on nothing else that is text.
 *
 * `to` is a route in this app; `href` is anywhere else, and the `external` variant opens it in
 * a new tab with a trailing mark and says so to a screen reader.
 */
export function TextLink({
    variant = 'inline',
    to,
    href,
    title,
    className,
    children,
}: {
    variant?: TextLinkVariant
    title?: string
    className?: string
    children: ReactNode
} & ({ to: string; href?: undefined } | { href: string; to?: undefined })) {
    const face = cn(
        'rounded-sm outline-none focus-visible:ring-2 focus-visible:ring-ring',
        VARIANTS[variant],
        className,
    )
    if (variant === 'external') {
        return (
            <a href={href ?? to} target="_blank" rel="noreferrer" title={title} className={face}>
                {children}
                <ICONS.external className="size-3 shrink-0" aria-hidden />
                <span className="sr-only">{LABELS.shell.new_tab}</span>
            </a>
        )
    }
    if (to !== undefined) {
        return (
            <Link to={to} title={title} className={face}>
                {children}
            </Link>
        )
    }
    return (
        <a href={href} title={title} className={face}>
            {children}
        </a>
    )
}
