import { Fragment, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router'

import { useStore } from '@/hooks/use-store'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { createStore } from '@/lib/store'
import { cn } from '@/lib/utils'

/** One step back: what it says, where it goes, and whether it wears the mono face. */
export interface Crumb {
    label: string
    to: string
    mono?: boolean
    /** What the crumb says on hover, where the crumb itself is a rendering of something else. */
    title?: string
}

/** Where in the top strip a screen's crumb is drawn, which the shell sets once it has mounted. */
export const crumbSlot = createStore<HTMLElement | null>(null)

/**
 * The trail back from a screen that is one thing to the listing it belongs to, drawn into the
 * shell's top strip rather than onto the page, so the page opens on its heading.
 *
 * The crumbs are the places above this one, every one a link. Below the breakpoint the last of
 * them stands alone, which is the way back, and the whole trail is the element's title. `inPlace`
 * draws it where it is rendered, which is what the design system's gallery does.
 */
export function Breadcrumb({ trail, inPlace = false }: { trail: readonly Crumb[]; inPlace?: boolean }) {
    const slot = useStore(crumbSlot)
    const nav: ReactNode = (
        <nav
            className="flex min-w-0 items-center gap-1.5 text-sm"
            aria-label={LABELS.shell.breadcrumb}
            title={trail.map((crumb) => crumb.label).join(' / ')}
        >
            {trail.map((crumb, index) => {
                const last = index === trail.length - 1
                return (
                    <Fragment key={`${crumb.label}-${String(index)}`}>
                        {index > 0 && (
                            <ICONS.expand
                                className="hidden size-3.5 shrink-0 text-faint md:block"
                                aria-hidden
                            />
                        )}
                        <Link
                            to={crumb.to}
                            title={crumb.title}
                            className={cn(
                                'min-w-0 truncate text-muted-foreground hover:text-foreground',
                                crumb.mono === true && 'font-mono text-xs',
                                !last && 'hidden md:inline',
                            )}
                        >
                            {crumb.label}
                        </Link>
                    </Fragment>
                )
            })}
        </nav>
    )
    if (inPlace) return nav
    return slot === null ? null : createPortal(nav, slot)
}
