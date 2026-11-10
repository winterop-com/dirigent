import { useRef } from 'react'

import { ResizeHandle } from '@winterop-com/sokkel-ui/ResizeHandle'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@winterop-com/sokkel-ui/primitives/tabs'
import { useStore } from '@/hooks/use-store'
import { LABELS } from '@/lib/labels'
import {
    PANEL_DEFAULT_WIDTH,
    PANEL_MAX_WIDTH,
    PANEL_MIN_WIDTH,
    panelTab,
    panelTabs,
    panelWidth,
    setPanelWidth,
} from '@/lib/panels'

/**
 * The right panel the shell holds: tabs over whatever the screen in front of it wants beside
 * itself, as a column beside the screen or as the shell's sheet over it.
 *
 * WHAT IS IN IT IS THE SCREEN'S. A screen fills it with `fillPanel` from an effect, and the shell
 * draws it only while a screen has. The open tab is held by id in a store, so a screen that gains
 * a tab does not move the reader to a different one, and `openPanelTab` can send somebody to one.
 *
 * Its left edge is dragged, moved by the arrow keys and reset by a double click, in pixels. Its
 * tab strip is as tall as the shell's top bar, and leaves the corner to the shell's toggle.
 */
export function RightPanel() {
    const width = useStore(panelWidth)
    const tabs = useStore(panelTabs)
    const chosen = useStore(panelTab)
    const aside = useRef<HTMLElement | null>(null)
    const active = tabs.some((tab) => tab.id === chosen) ? (chosen ?? tabs[0]?.id) : tabs[0]?.id

    return (
        <>
            <ResizeHandle
                target={aside}
                size={width}
                onSize={setPanelWidth}
                reset={PANEL_DEFAULT_WIDTH}
                min={PANEL_MIN_WIDTH}
                max={PANEL_MAX_WIDTH}
                grows={-1}
                label={LABELS.shell.resize_panel}
            />
            <aside
                ref={aside}
                className="flex h-full shrink-0 flex-col border-l border-border-strong bg-sidebar"
                style={{ width }}
            >
                <Tabs
                    value={active}
                    onValueChange={(value) => {
                        panelTab.set(String(value))
                    }}
                    className="flex min-h-0 flex-1 flex-col gap-0"
                >
                    <div
                        data-shell-strip="top"
                        className="flex h-shell-top shrink-0 items-center gap-2 border-b border-border-strong pr-12 pl-2"
                    >
                        <TabsList>
                            {tabs.map((tab) => (
                                <TabsTrigger key={tab.id} value={tab.id}>
                                    {tab.label}
                                </TabsTrigger>
                            ))}
                        </TabsList>
                    </div>
                    {tabs.map((tab) => (
                        <TabsContent key={tab.id} value={tab.id} className="min-h-0 flex-1 overflow-y-auto">
                            {tab.render()}
                        </TabsContent>
                    ))}
                </Tabs>
            </aside>
        </>
    )
}
