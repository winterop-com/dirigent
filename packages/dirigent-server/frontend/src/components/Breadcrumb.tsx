import { Fragment } from 'react'
import { Link } from 'react-router'

import { cn } from '@/lib/utils'

/** One step of a trail: what it says, where it goes, and whether it wears the mono face. */
export interface Crumb {
    label: string
    /** Where the crumb goes; a leaf goes nowhere. */
    to?: string
    mono?: boolean
    /**
     * Keep this crumb on screen below the breakpoint.
     *
     * The crumb carrying the thing's code, where the leaf is not it: the code is on screen on
     * every screen, and a trail cut back to its leaf would take it off this one.
     */
    keep?: boolean
    /** What the crumb says on hover, where the crumb itself is a rendering of something else. */
    title?: string
}

/**
 * The trail across the top of a screen that is one thing rather than a listing.
 *
 * BELOW THE BREAKPOINT IT IS ITS LEAF. A trail of three crumbs and two separators wraps a
 * 390px strip onto a second line, so what is drawn there is the leaf -- plus whatever crumb
 * says the code -- and the whole trail is the element's title. The leaf truncates; the strip
 * stays one line.
 */
export function Breadcrumb({ trail, code }: { trail: readonly Crumb[]; code?: string | null }) {
    return (
        <nav
            className="flex min-w-0 items-center gap-1.5 text-sm"
            aria-label="Breadcrumb"
            title={trail.map((crumb) => crumb.label).join(' / ')}
        >
            {trail.map((crumb, index) => {
                const leaf = index === trail.length - 1
                const shown = leaf || crumb.keep === true
                // The separator belongs to the crumbs either side of it: drawn below the
                // breakpoint only where both of them are.
                const behind = trail.slice(0, index).some((earlier) => earlier.keep === true)
                return (
                    <Fragment key={`${crumb.label}-${String(index)}`}>
                        {index > 0 && (
                            <span className={cn('text-faint', !(shown && behind) && 'hidden md:inline')} aria-hidden>
                                /
                            </span>
                        )}
                        {crumb.to === undefined ? (
                            <span
                                title={crumb.title}
                                className={cn(
                                    'min-w-0 truncate',
                                    leaf && 'font-medium',
                                    crumb.mono === true && 'font-mono',
                                    !shown && 'hidden md:inline',
                                )}
                            >
                                {crumb.label}
                            </span>
                        ) : (
                            <Link
                                to={crumb.to}
                                title={crumb.title}
                                className={cn(
                                    'text-muted-foreground hover:text-foreground min-w-0 truncate',
                                    crumb.mono === true && 'font-mono',
                                    !shown && 'hidden md:inline',
                                )}
                            >
                                {crumb.label}
                            </Link>
                        )}
                    </Fragment>
                )
            })}
            {code !== undefined && code !== null && (
                <span className="text-muted-foreground min-w-0 truncate font-mono text-xs">{code}</span>
            )}
        </nav>
    )
}
