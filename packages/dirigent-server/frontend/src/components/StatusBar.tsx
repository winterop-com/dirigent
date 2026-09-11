import { Settings } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { useStore } from '@/hooks/use-store'
import { authStore } from '@/lib/auth'
import { RAIL_COLLAPSED_WIDTH, railCollapsed, railDragging, railWidth } from '@/lib/panels'
import { screenStatus, type StatusTone } from '@/lib/screen-status'
import { cn } from '@/lib/utils'

export const SETTINGS_LABEL = 'Settings'

/**
 * The line along the foot of the app: settings, who this is, and what the screen is doing.
 *
 * ONE ELEMENT ACROSS THE WHOLE WIDTH, WITH CELLS INSIDE IT. The rail's foot and the status
 * line were two elements each drawing its own top border, and two borders meeting at a column
 * edge is a rule that can come apart -- a pixel of rounding, a rung changed on one of them,
 * and the bottom of the app reads as a step. So the border is drawn once, by the bar; the
 * divider between the cells is drawn inside it; and the settings cell is the rail's width
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
 * WHAT THIS INSTANCE IS BELONGS TO THE CORNER, NOT HERE. A fact appears once in the shell, and
 * the identity in the topbar already carries the name, the environment and the version.
 */

/** How each tone is inked. A live stream is information, not a warning. */
const TONE: Record<StatusTone, string> = {
    live: 'text-info',
    quiet: 'text-muted-foreground',
    warn: 'text-warning',
}

export function StatusBar({ onSettings }: { onSettings: () => void }) {
    const auth = useStore(authStore)
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
                data-shell-cell="settings"
                className={cn(
                    'hidden shrink-0 items-stretch border-r border-border-strong md:flex',
                    // The cell is the rail's width, so it moves the way the rail moves: the
                    // collapse animates, and a drag is followed raw.
                    !dragging && 'transition-[width] duration-200',
                    collapsed && 'justify-center',
                )}
                style={{ width: collapsed ? RAIL_COLLAPSED_WIDTH : width }}
            >
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                variant="ghost"
                                onClick={onSettings}
                                aria-label={SETTINGS_LABEL}
                                className={cn(
                                    'h-full w-full rounded-none text-xs text-muted-foreground hover:text-foreground',
                                    collapsed ? 'justify-center p-0' : 'justify-start gap-3 px-4',
                                )}
                            >
                                <Settings className="size-4 shrink-0" aria-hidden />
                                {!collapsed && <span>{SETTINGS_LABEL}</span>}
                            </Button>
                        }
                    />
                    <TooltipContent side="top">{SETTINGS_LABEL}</TooltipContent>
                </Tooltip>
            </div>

            <div data-shell-cell="status" className="flex min-w-0 flex-1 items-center gap-3 px-3">
                {auth.identity !== null && (
                    <span className="font-mono text-xs text-muted-foreground">{auth.identity.username}</span>
                )}
                {status.note !== null && (
                    <span className={cn('truncate text-xs', TONE[status.tone])}>{status.note}</span>
                )}
                <div className="flex-1" />
                {status.identifier !== null && <span className="identifier">{status.identifier}</span>}
            </div>
        </footer>
    )
}
