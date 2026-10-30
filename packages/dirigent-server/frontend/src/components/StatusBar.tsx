import { AccountMenu } from '@/components/AccountMenu'
import { useStore } from '@/hooks/use-store'
import { RAIL_COLLAPSED_WIDTH, railCollapsed, railDragging, railWidth } from '@/lib/panels'
import { screenStatus, type StatusTone } from '@/lib/screen-status'
import { cn } from '@/lib/utils'

/**
 * The line along the foot of the app: the account, and what the screen is doing.
 *
 * ONE ELEMENT ACROSS THE WHOLE WIDTH, WITH CELLS INSIDE IT. The rail's foot and the status
 * line were two elements each drawing its own top border, and two borders meeting at a column
 * edge is a rule that can come apart -- a pixel of rounding, a rung changed on one of them,
 * and the bottom of the app reads as a step. So the border is drawn once, by the bar; the
 * divider between the cells is drawn inside it; and the account cell is the rail's width
 * because it reads the same store the rail does, drag and collapse included.
 *
 * ONE ROW, ALWAYS THE SAME HEIGHT, whatever it happens to be saying. A bar that grew when it
 * had something to report would move the page under it, so what it holds is short facts and
 * never a sentence.
 *
 * TWO OF THEM ARE THE SCREEN'S. A screen states a note and an identifier through
 * `lib/screen-status` while it is mounted -- where a run's one event stream is, and the trace
 * the run is on -- and the bar draws them without knowing which screen wrote them.
 *
 * HOW THIS INSTANCE IS DOING BELONGS TO THE TOP BAR'S DOT, NOT HERE. A fact appears once in the
 * shell.
 */

/** How each tone is inked. A live stream is information, not a warning. */
const TONE: Record<StatusTone, string> = {
    live: 'text-info',
    quiet: 'text-muted-foreground',
    warn: 'text-warning',
}

export function StatusBar({ onSettings, onShortcuts }: { onSettings: () => void; onShortcuts: () => void }) {
    const status = useStore(screenStatus)
    const collapsed = useStore(railCollapsed)
    const width = useStore(railWidth)
    const dragging = useStore(railDragging)

    return (
        <footer
            data-shell-strip="foot"
            className="flex h-shell-foot shrink-0 items-stretch border-t border-border-strong bg-sidebar"
        >
            <div
                data-shell-cell="account"
                className={cn(
                    'hidden shrink-0 items-stretch border-r border-border-strong md:flex',
                    // The cell is the rail's width, so it moves the way the rail moves: the
                    // collapse animates, and a drag is followed raw.
                    !dragging && 'transition-[width] duration-200',
                    collapsed && 'justify-center',
                )}
                style={{ width: collapsed ? RAIL_COLLAPSED_WIDTH : width }}
            >
                <AccountMenu
                    collapsed={collapsed}
                    className="h-full w-full rounded-none"
                    onSettings={onSettings}
                    onShortcuts={onShortcuts}
                />
            </div>

            <div data-shell-cell="status" className="flex min-w-0 flex-1 items-center gap-3 px-3">
                {status.note !== null && (
                    <span className={cn('truncate text-xs', TONE[status.tone])}>{status.note}</span>
                )}
                <div className="flex-1" />
                {status.identifier !== null && <span className="identifier">{status.identifier}</span>}
            </div>
        </footer>
    )
}
