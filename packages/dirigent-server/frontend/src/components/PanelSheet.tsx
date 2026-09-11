import { X } from 'lucide-react'
import { useEffect } from 'react'

import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useSmallScreen } from '@/hooks/use-small-screen'
import { useStore } from '@/hooks/use-store'
import { closeSheet, openPanelTab, panelSheet, panelTab, panelTabs } from '@/lib/panels'
import { cn } from '@/lib/utils'

export const CLOSE_PANEL_LABEL = 'Close the panel'

/**
 * The right panel, below the breakpoint the right panel is not drawn at.
 *
 * A 360px column beside a 390px screen is not a column, so what is beside a screen becomes
 * what is under it: a bar across the foot carrying the tabs the screen filled, and a sheet
 * over the whole screen when one of them is asked for. The graph screens keep the graph, and
 * choosing a step raises the sheet on that step's own tab -- the same `openPanelTab` the
 * desktop panel answers.
 *
 * A SCREEN THAT FILLS NO PANEL HAS NO BAR. Nothing wears chrome unless it does something.
 */
export function PanelSheet() {
    const small = useSmallScreen()
    const tabs = useStore(panelTabs)
    const open = useStore(panelSheet)
    const chosen = useStore(panelTab)

    useEffect(() => {
        if (!open) return
        const escape = (event: KeyboardEvent) => {
            if (event.key === 'Escape') closeSheet()
        }
        document.addEventListener('keydown', escape)
        return () => {
            document.removeEventListener('keydown', escape)
        }
    }, [open])

    if (!small || tabs.length === 0) return null

    const active = tabs.some((tab) => tab.id === chosen) ? (chosen ?? tabs[0]?.id) : tabs[0]?.id

    return (
        <>
            <div
                data-panel-bar
                className="flex h-shell-foot shrink-0 items-stretch border-t border-border-strong bg-sidebar"
            >
                {tabs.map((tab) => (
                    <button
                        key={tab.id}
                        type="button"
                        onClick={() => {
                            openPanelTab(tab.id)
                        }}
                        className={cn(
                            'min-h-10 flex-1 truncate px-2 text-xs text-muted-foreground hover:text-foreground',
                            open && tab.id === active && 'font-medium text-foreground',
                        )}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {open && (
                <div data-panel-sheet className="fixed inset-0 z-40 flex flex-col bg-sidebar">
                    <Tabs
                        value={active}
                        onValueChange={(value) => {
                            panelTab.set(String(value))
                        }}
                        className="flex min-h-0 flex-1 flex-col gap-0"
                    >
                        <div className="flex h-shell-top shrink-0 items-center gap-2 border-b border-border-strong px-2">
                            <TabsList>
                                {tabs.map((tab) => (
                                    <TabsTrigger key={tab.id} value={tab.id}>
                                        {tab.label}
                                    </TabsTrigger>
                                ))}
                            </TabsList>
                            <Button
                                variant="ghost"
                                size="icon"
                                aria-label={CLOSE_PANEL_LABEL}
                                onClick={closeSheet}
                                className="ml-auto shrink-0 text-muted-foreground"
                            >
                                <X className="size-4" aria-hidden />
                            </Button>
                        </div>
                        {tabs.map((tab) => (
                            <TabsContent
                                key={tab.id}
                                value={tab.id}
                                className="min-h-0 flex-1 overflow-y-auto"
                            >
                                {tab.render()}
                            </TabsContent>
                        ))}
                    </Tabs>
                </div>
            )}
        </>
    )
}
