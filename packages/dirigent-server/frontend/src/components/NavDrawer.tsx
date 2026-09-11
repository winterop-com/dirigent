import { Settings, Waypoints, X } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { NavLink, useLocation } from 'react-router'

import { RailEntry } from '@/components/Rail'
import { Button } from '@/components/ui/button'
import { useStore } from '@/hooks/use-store'
import { authStore } from '@/lib/auth'
import { DASHBOARD_PATH, sectionsFor } from '@/lib/nav'
import { cn } from '@/lib/utils'

export const OPEN_NAV_LABEL = 'Open navigation'
export const CLOSE_NAV_LABEL = 'Close navigation'

/** What the drawer's foot offers, which is the cell the status bar carries above the breakpoint. */
const SETTINGS_LABEL = 'Settings'

/**
 * The rail, below the breakpoint the rail is not drawn at.
 *
 * A 240px column on a 390px screen is most of the screen, so below `md` the navigation is a
 * drawer over the work rather than a column beside it: off screen until the menu button in the
 * top strip asks for it, and closed by its own control, by Escape, by the scrim, and by
 * arriving somewhere -- a drawer still standing over the screen somebody navigated to is one
 * they have to dismiss twice.
 *
 * THE ENTRIES ARE THE RAIL'S OWN. `RailEntry` draws a row here exactly as it draws one there,
 * so an entry added to `lib/nav` arrives in both without either being told.
 *
 * SETTINGS IS AT THE FOOT, because the status bar's settings cell is the rail's width and is
 * not drawn below the breakpoint at all.
 */
export function NavDrawer({
    open,
    onClose,
    onSettings,
}: {
    open: boolean
    onClose: () => void
    onSettings: () => void
}) {
    const auth = useStore(authStore)
    const sections = sectionsFor(auth.identity?.role ?? null)
    const close = useRef<HTMLButtonElement | null>(null)
    const { pathname } = useLocation()

    // Focus lands in the drawer on open: a sheet over the screen that left the focus behind it
    // is a sheet a keyboard cannot reach. Returning it is the opener's, which holds that ref.
    //
    // TWO FRAMES, because a hidden element takes no focus: the class that stops hiding the
    // drawer is resolved on the frame after the render, and the control inside it is focusable
    // only once that has happened.
    useEffect(() => {
        if (!open) return
        let second = 0
        const first = requestAnimationFrame(() => {
            second = requestAnimationFrame(() => {
                close.current?.focus()
            })
        })
        return () => {
            cancelAnimationFrame(first)
            cancelAnimationFrame(second)
        }
    }, [open])

    useEffect(() => {
        if (!open) return
        const escape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') onClose()
        }
        document.addEventListener('keydown', escape)
        return () => {
            document.removeEventListener('keydown', escape)
        }
    }, [onClose, open])

    // The path is what closes it, not the click: a palette action and a link have to leave the
    // drawer the same way.
    const closeRef = useRef(onClose)
    useEffect(() => {
        closeRef.current = onClose
    }, [onClose])
    useEffect(() => {
        closeRef.current()
    }, [pathname])

    return (
        <div className="md:hidden" inert={!open}>
            <div
                data-nav-scrim
                onClick={onClose}
                aria-hidden
                className={cn(
                    'fixed inset-0 z-40 bg-black/40 transition-opacity duration-150',
                    open ? 'opacity-100' : 'pointer-events-none opacity-0',
                )}
            />
            <aside
                data-nav-drawer
                aria-label="Navigation"
                className={cn(
                    'fixed inset-y-0 left-0 z-50 flex w-72 max-w-[85vw] flex-col border-r border-border-strong bg-sidebar text-sidebar-foreground transition-[translate] duration-200',
                    open ? 'translate-x-0' : 'invisible -translate-x-full',
                )}
            >
                <div className="flex h-shell-top shrink-0 items-center gap-2 px-3">
                    <NavLink
                        to={DASHBOARD_PATH}
                        aria-label="dirigent"
                        className="flex items-center gap-2 rounded-md focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
                    >
                        <span className="flex size-7 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground">
                            <Waypoints className="size-4" aria-hidden />
                        </span>
                        <span className="text-base font-semibold tracking-tight">dirigent</span>
                    </NavLink>
                    <Button
                        ref={close}
                        variant="ghost"
                        size="icon"
                        aria-label={CLOSE_NAV_LABEL}
                        onClick={onClose}
                        className="ml-auto shrink-0 text-muted-foreground"
                    >
                        <X className="size-4" aria-hidden />
                    </Button>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto border-t border-border-strong pt-1 pb-2">
                    {sections.map((section) => (
                        <nav key={section.id} className="flex flex-col gap-1 px-2 pb-3">
                            {section.label !== null && (
                                <p className="px-2 pt-4 pb-1.5 text-xs font-medium tracking-wide text-faint uppercase">
                                    {section.label}
                                </p>
                            )}
                            {section.entries.map((entry) => (
                                <RailEntry key={entry.path} entry={entry} collapsed={false} />
                            ))}
                        </nav>
                    ))}
                </div>

                <div className="shrink-0 border-t border-border-strong p-2">
                    <Button
                        variant="ghost"
                        onClick={() => {
                            onClose()
                            onSettings()
                        }}
                        className="w-full justify-start gap-3 px-3 text-muted-foreground hover:text-foreground"
                    >
                        <Settings className="size-4 shrink-0" aria-hidden />
                        {SETTINGS_LABEL}
                    </Button>
                </div>
            </aside>
        </div>
    )
}
