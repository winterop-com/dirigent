import { useStore } from '@/hooks/use-store'
import { openPanelTab, panelSheet, panelTab, panelTabs } from '@/lib/panels'
import { cn } from '@/lib/utils'

/**
 * The right panel's tabs across the foot below the breakpoint, each raising the panel's sheet on
 * that tab. The graph screens keep the graph, and what is beside them is a tap away.
 *
 * A SCREEN THAT FILLS NO PANEL HAS NO BAR. Nothing wears chrome unless it does something.
 */
export function PanelBar() {
    const tabs = useStore(panelTabs)
    const open = useStore(panelSheet)
    const chosen = useStore(panelTab)
    if (tabs.length === 0) return null
    const active = tabs.some((tab) => tab.id === chosen) ? (chosen ?? tabs[0]?.id) : tabs[0]?.id

    return (
        <div data-panel-bar className="flex shrink-0 items-stretch border-t border-border-strong bg-sidebar">
            {tabs.map((tab) => (
                <button
                    key={tab.id}
                    type="button"
                    onClick={() => {
                        openPanelTab(tab.id)
                    }}
                    className={cn(
                        'min-h-finger flex-1 truncate px-2 text-xs text-muted-foreground hover:text-foreground',
                        open && tab.id === active && 'font-medium text-foreground',
                    )}
                >
                    {tab.label}
                </button>
            ))}
        </div>
    )
}
