import { PanelLeftClose, PanelLeftOpen, Waypoints } from 'lucide-react'
import { NavLink } from 'react-router'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useEffect, useRef, type PointerEvent as ReactPointerEvent } from 'react'

import { useDragSize } from '@/hooks/use-drag-size'
import { useStore } from '@/hooks/use-store'
import { authStore } from '@/lib/auth'
import { DASHBOARD_PATH, marksOnlyItself, sectionsFor, type NavEntry } from '@/lib/nav'
import {
    RAIL_COLLAPSED_WIDTH,
    RAIL_MAX_WIDTH,
    RAIL_MIN_WIDTH,
    clampRailWidth,
    railCollapsed,
    railDragging,
    railWidth,
    setRailWidth,
    toggleRail,
} from '@/lib/panels'
import { cn } from '@/lib/utils'

export const COLLAPSE_LABEL = 'Collapse the navigation'
export const RESIZE_RAIL_LABEL = 'Resize the navigation'

/** How far one arrow press moves an edge. */
const KEYBOARD_STEP = 16
export const EXPAND_LABEL = 'Expand the navigation'

/**
 * The navigation rail: every screen this account is offered, in one column.
 *
 * Expanded it shows labels at a width the grip on its right edge drags, kept in pixels the
 * way the right panel's is; collapsed it is 56px of icons and the labels come back as
 * tooltips, and the grip goes with them.
 *
 * ONE LINE PER ENTRY. Pipelines, Runs, Schedules, Connections and Blocks are what this app is
 * made of, and a word that says what it is needs no gloss under it. The line each entry carries
 * about itself is the palette's, where a reader is searching rather than recognising.
 *
 * The active entry wears a left border rather than a filled overlay, because the border
 * survives the collapse: a strip of icons has no room for a fill that reads as anything.
 *
 * SETTINGS SITS UNDER THE RAIL, in the bar along the foot of the app -- a destination like
 * every other entry rather than one more icon in a topbar of them, and in the same place
 * however long the navigation grows. The bar owns that cell, and this column ends above it,
 * because one element drawing the whole bottom rule is a rule that cannot come apart.
 *
 * THE HEAD IS THE SHELL'S TOP STRIP, NOT THIS COLUMN'S: `h-shell-top`, the same as the topbar
 * and the panel's tab strip, and the rule under all three is drawn once by the shell.
 */
export function Rail() {
    const collapsed = useStore(railCollapsed)
    const width = useStore(railWidth)
    const auth = useStore(authStore)
    const sections = sectionsFor(auth.identity?.role ?? null)
    const aside = useRef<HTMLElement | null>(null)
    const { dragging, beginResize } = useDragSize('x', width, 1, setRailWidth, clampRailWidth, aside)

    useEffect(() => {
        railDragging.set(dragging)
    }, [dragging])

    // A collapsed rail wakes on a drag: pull its edge outward and it expands under the hand,
    // committing whatever width the release expressed. A click without a pull stays a click.
    const wake = (event: ReactPointerEvent<HTMLDivElement>) => {
        event.preventDefault()
        event.currentTarget.setPointerCapture(event.pointerId)
        const startX = event.clientX
        let woke = false
        const widthAt = (clientX: number) =>
            clampRailWidth(Math.max(RAIL_MIN_WIDTH, RAIL_COLLAPSED_WIDTH + (clientX - startX)))
        const follow = (move: globalThis.PointerEvent) => {
            if (!woke && move.clientX - startX > 8) {
                woke = true
                toggleRail()
            }
            if (woke && aside.current !== null) {
                aside.current.style.transition = 'none'
                aside.current.style.width = `${String(widthAt(move.clientX))}px`
            }
        }
        const done = (up: globalThis.PointerEvent) => {
            document.removeEventListener('pointermove', follow)
            document.removeEventListener('pointerup', done)
            if (!woke) return
            if (aside.current !== null) {
                aside.current.style.transition = ''
                aside.current.style.width = ''
            }
            setRailWidth(widthAt(up.clientX))
        }
        document.addEventListener('pointermove', follow)
        document.addEventListener('pointerup', done)
    }

    return (
        <>
        <aside
            ref={aside}
            className={cn(
                'bg-sidebar text-sidebar-foreground border-border-strong relative hidden shrink-0 flex-col overflow-hidden border-r md:flex',
                !dragging && 'transition-[width] duration-200',
            )}
            style={{ width: collapsed ? RAIL_COLLAPSED_WIDTH : width }}
        >
            {/* COLLAPSED, THE MARK IS THE TOGGLE. There is no room beside a 28px mark in a
                56px strip that does not read as a cram, so the mark itself expands the rail,
                showing the expand glyph under the hand -- and loses nothing as a link, because
                Home is the first entry right below it. Expanded, the mark is the home link and
                the collapse control sits beside the wordmark, where it always was. */}
            <div
                data-shell-strip="top"
                className={cn(
                    'flex h-shell-top shrink-0 items-center gap-2 px-3',
                    collapsed && 'justify-center px-0',
                )}
            >
                {collapsed ? (
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <button
                                    type="button"
                                    onClick={toggleRail}
                                    aria-label={EXPAND_LABEL}
                                    className="focus-visible:ring-ring/50 group/mark bg-primary text-primary-foreground flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-md focus-visible:ring-[3px] focus-visible:outline-none"
                                >
                                    <Waypoints className="size-4 group-hover/mark:hidden" aria-hidden />
                                    <PanelLeftOpen className="hidden size-4 group-hover/mark:block" aria-hidden />
                                </button>
                            }
                        />
                        <TooltipContent side="right">{EXPAND_LABEL}</TooltipContent>
                    </Tooltip>
                ) : (
                    <>
                        <NavLink
                            to={DASHBOARD_PATH}
                            aria-label="dirigent"
                            className="focus-visible:ring-ring/50 flex items-center gap-2 rounded-md focus-visible:ring-[3px] focus-visible:outline-none"
                        >
                            <span className="bg-primary text-primary-foreground flex size-7 shrink-0 items-center justify-center rounded-md">
                                <Waypoints className="size-4" aria-hidden />
                            </span>
                            <span className="text-base font-semibold tracking-tight">dirigent</span>
                        </NavLink>
                        <Tooltip>
                            <TooltipTrigger
                                render={
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={toggleRail}
                                        aria-label={COLLAPSE_LABEL}
                                        className="text-muted-foreground ml-auto shrink-0"
                                    >
                                        <PanelLeftClose className="size-4" aria-hidden />
                                    </Button>
                                }
                            />
                            <TooltipContent side="right">{COLLAPSE_LABEL}</TooltipContent>
                        </Tooltip>
                    </>
                )}
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto pt-1 pb-2">
                {sections.map((section) => (
                    <nav key={section.id} className="flex flex-col gap-1 px-2 pb-3">
                        {section.label !== null && !collapsed && (
                            <p className="text-faint px-2 pt-4 pb-1.5 text-xs font-medium tracking-wide uppercase">
                                {section.label}
                            </p>
                        )}
                        {section.label !== null && collapsed && <div className="border-border mx-2 my-2 border-t" />}
                        {section.entries.map((entry) => (
                            <RailEntry key={entry.path} entry={entry} collapsed={collapsed} />
                        ))}
                    </nav>
                ))}
            </div>

        </aside>
        {(
            <div
                role="separator"
                aria-orientation="vertical"
                aria-label={collapsed ? EXPAND_LABEL : RESIZE_RAIL_LABEL}
                aria-valuenow={collapsed ? RAIL_COLLAPSED_WIDTH : width}
                aria-valuemin={RAIL_MIN_WIDTH}
                aria-valuemax={RAIL_MAX_WIDTH}
                tabIndex={0}
                data-dragging={dragging}
                onPointerDown={collapsed ? wake : beginResize}
                onKeyDown={(event) => {
                    if (event.key === 'ArrowRight') setRailWidth(width + KEYBOARD_STEP)
                    else if (event.key === 'ArrowLeft') setRailWidth(width - KEYBOARD_STEP)
                    else return
                    event.preventDefault()
                }}
                className="resize-handle z-10 hidden w-1.5 shrink-0 cursor-col-resize touch-none md:block"
            />
        )}
        </>
    )
}

export function RailEntry({ entry, collapsed }: { entry: NavEntry; collapsed: boolean }) {
    const Icon = entry.icon
    const link = (
        <NavLink
            to={entry.path}
            end={marksOnlyItself(entry.path)}
            aria-label={entry.label}
            className={({ isActive }) =>
                cn(
                    'flex items-center gap-3 rounded-r-md rounded-l-sm border-l-2 px-3 py-2 text-sm transition-colors',
                    collapsed && 'mx-auto size-9 justify-center rounded-md border-l-0 p-0',
                    isActive
                        ? 'border-sidebar-primary bg-sidebar-accent text-sidebar-accent-foreground font-medium'
                        : 'text-muted-foreground hover:bg-secondary hover:text-foreground border-transparent',
                )
            }
        >
            <Icon className="size-4 shrink-0" aria-hidden />
            {!collapsed && <span>{entry.label}</span>}
        </NavLink>
    )
    if (!collapsed) return link
    return (
        <Tooltip>
            <TooltipTrigger render={link} />
            <TooltipContent side="right">{entry.label}</TooltipContent>
        </Tooltip>
    )
}
