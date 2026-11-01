import { useRef } from 'react'
import { NavLink } from 'react-router'

import { AccountMenu } from '@/components/AccountMenu'
import { useDragSize } from '@/hooks/use-drag-size'
import { useStore } from '@/hooks/use-store'
import { authStore } from '@/lib/auth'
import { ICONS } from '@/lib/icons'
import { LABELS } from '@/lib/labels'
import { DASHBOARD_PATH, marksOnlyItself, sectionsFor, type NavEntry, type NavSection } from '@/lib/nav'
import {
    RAIL_MAX_WIDTH,
    RAIL_MIN_WIDTH,
    clampRailWidth,
    railHidden,
    railWidth,
    resetRailWidth,
    setRailWidth,
} from '@/lib/panels'

export const RESIZE_RAIL_LABEL = LABELS.shell.resize_nav

/** How far one arrow key moves the rail's edge. */
const KEYBOARD_STEP = 16

/**
 * The navigation rail: the brand at its head, every screen this account is offered as one word
 * each, and the account at its foot.
 *
 * Its head is `h-shell-top`, the same as the top strip beside it. Hidden, it draws nothing, and
 * the top strip carries the control that brings it back. Its right edge is a separator that a
 * pointer drags and the arrow keys move, and a double-click on it gives back the width it opens at.
 */
export function Rail({ onSettings, onShortcuts }: { onSettings: () => void; onShortcuts: () => void }) {
    const hidden = useStore(railHidden)
    const auth = useStore(authStore)
    const width = useStore(railWidth)
    const aside = useRef<HTMLElement | null>(null)
    const { dragging, beginResize } = useDragSize('x', width, 1, setRailWidth, clampRailWidth, aside)
    const sections = sectionsFor(auth.identity?.role ?? null)
    if (hidden) return null

    return (
        <>
            <aside
                ref={aside}
                className="hidden shrink-0 flex-col bg-sidebar text-sidebar-foreground md:flex"
                style={{ width }}
            >
                <div data-shell-strip="top" className="flex h-shell-top shrink-0 items-center px-3.5">
                    <BrandLink />
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto px-3.5 pb-2">
                    {sections.map((section) => (
                        <nav key={section.id} className="flex flex-col gap-px">
                            {section.label !== null && <SectionLabel section={section} />}
                            {section.entries.map((entry) => (
                                <RailEntry key={entry.path} entry={entry} />
                            ))}
                        </nav>
                    ))}
                </div>

                <div className="shrink-0 px-3.5 pt-2 pb-4">
                    <AccountMenu className="w-full" onSettings={onSettings} onShortcuts={onShortcuts} />
                </div>
            </aside>
            <div
                role="separator"
                aria-orientation="vertical"
                aria-label={RESIZE_RAIL_LABEL}
                aria-valuenow={width}
                aria-valuemin={RAIL_MIN_WIDTH}
                aria-valuemax={RAIL_MAX_WIDTH}
                tabIndex={0}
                data-dragging={dragging}
                onPointerDown={beginResize}
                onDoubleClick={resetRailWidth}
                onKeyDown={(event) => {
                    if (event.key === 'ArrowRight') setRailWidth(width + KEYBOARD_STEP)
                    else if (event.key === 'ArrowLeft') setRailWidth(width - KEYBOARD_STEP)
                    else if (event.key === 'Home') setRailWidth(RAIL_MIN_WIDTH)
                    else if (event.key === 'End') setRailWidth(RAIL_MAX_WIDTH)
                    else return
                    event.preventDefault()
                }}
                className="resize-handle z-10 -mr-1.5 hidden w-1.5 shrink-0 cursor-col-resize touch-none md:block"
            />
        </>
    )
}

/** The brand tile and the wordmark, which is the way to the dashboard. */
export function BrandLink() {
    return (
        <NavLink
            to={DASHBOARD_PATH}
            aria-label={LABELS.shell.wordmark}
            className="control-link flex items-center gap-2.5 rounded-control px-1.5 focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
        >
            <span className="flex size-7 shrink-0 items-center justify-center rounded-node bg-brand text-brand-foreground">
                <ICONS.brand className="size-4" aria-hidden />
            </span>
            <span className="text-lockup">{LABELS.shell.wordmark}</span>
        </NavLink>
    )
}

/** A group's heading. */
export function SectionLabel({ section }: { section: NavSection }) {
    return (
        <p className="px-2.5 pt-4.5 pb-1.5 text-xs tracking-widest text-faint uppercase">{section.label}</p>
    )
}

export function RailEntry({ entry }: { entry: NavEntry }) {
    return (
        <NavLink
            to={entry.path}
            end={marksOnlyItself(entry.path)}
            className="control-link rail-entry flex items-center rounded-control px-2.5 py-1.5 text-sm transition-colors"
        >
            {entry.label}
        </NavLink>
    )
}
