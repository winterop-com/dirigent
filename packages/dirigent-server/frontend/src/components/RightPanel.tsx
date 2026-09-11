import { useRef } from 'react'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useDragSize } from '@/hooks/use-drag-size'
import { useSmallScreen } from '@/hooks/use-small-screen'
import { useStore } from '@/hooks/use-store'
import {
    clampPanelWidth,
    PANEL_MAX_WIDTH,
    PANEL_MIN_WIDTH,
    panelOpen,
    panelTab,
    panelTabs,
    panelWidth,
    setPanelWidth,
} from '@/lib/panels'
import { cn } from '@/lib/utils'

export const RESIZE_PANEL_LABEL = 'Resize the side panel'

/** What the strip says when there are no tabs, which is a label rather than a tab. */
export const EMPTY_HEADING = 'Panel'

/** How far one arrow key moves the edge. A keyboard has to be able to do what the pointer does. */
const KEYBOARD_STEP = 16

/** What the panel says when the screen in front of it has filled none of it. */
const NOTHING_HERE = 'Nothing selected.'

/**
 * The right panel: tabs over whatever the screen in front of it wants beside itself.
 *
 * DRAGGED IN PIXELS. The handle writes a width, not a fraction -- see `lib/panels` for why --
 * and the drag is followed on the document rather than on the handle, so the pointer leaving
 * the 6px strip mid-drag does not drop it.
 *
 * THE HANDLE IS A SEPARATOR AND ANSWERS THE ARROW KEYS, because a drag is not available to
 * everybody and a panel that can only be sized by pointer is a panel some people cannot size.
 *
 * WHAT IS IN IT IS THE SCREEN'S. The panel is drawn once, here, and a screen fills it with
 * `fillPanel` from an effect; a screen that fills nothing gets the line saying so. The open tab
 * is held by id rather than by position, so a screen that gains a tab does not move the reader
 * to a different one -- and it is a store rather than this component's own state, because a
 * screen sometimes has to send somebody to a particular tab through `openPanelTab`.
 *
 * NOTHING WEARS INTERACTIVE CHROME UNLESS IT DOES SOMETHING. A screen that filled no tabs has
 * no tabs, so the strip carries a plain label rather than one lone tab shaped like a control
 * that cannot be pressed and would do nothing if it could.
 *
 * ITS TAB STRIP IS THE SHELL'S TOP STRIP. `h-shell-top` and the strong border, the same as the
 * rail's head and the topbar, so the rule across the top of the app does not step where the
 * panel begins -- and its close control sits on the line the topbar's own toggle sits on.
 */
export function RightPanel() {
    const open = useStore(panelOpen)
    const width = useStore(panelWidth)
    const tabs = useStore(panelTabs)
    const chosen = useStore(panelTab)
    const aside = useRef<HTMLElement | null>(null)
    const small = useSmallScreen()
    const { dragging, beginResize } = useDragSize('x', width, -1, setPanelWidth, clampPanelWidth, aside)

    // An unfilled panel is not a panel: a screen that offers nothing beside itself gets the
    // full width, and the empty chrome never has to say "nothing selected". A filled one
    // stays mounted while closed, at no width, so the toggle slides the way the rail does.
    // Below the breakpoint what is beside a screen is under it instead, and `PanelSheet` is
    // what draws it. Hiding this column with a class would leave every tab mounted twice.
    if (small || tabs.length === 0) return null

    const active = tabs.some((tab) => tab.id === chosen) ? (chosen ?? tabs[0]?.id) : tabs[0]?.id

    return (
        <>
            {open && (
                <div
                    role="separator"
                    aria-orientation="vertical"
                    aria-label={RESIZE_PANEL_LABEL}
                    aria-valuenow={width}
                    aria-valuemin={PANEL_MIN_WIDTH}
                    aria-valuemax={PANEL_MAX_WIDTH}
                    tabIndex={0}
                    data-dragging={dragging}
                    onPointerDown={beginResize}
                    onKeyDown={(event) => {
                        if (event.key === 'ArrowLeft') setPanelWidth(width + KEYBOARD_STEP)
                        else if (event.key === 'ArrowRight') setPanelWidth(width - KEYBOARD_STEP)
                        else return
                        event.preventDefault()
                    }}
                    className="resize-handle z-10 hidden w-1.5 shrink-0 cursor-col-resize touch-none md:block"
                />
            )}
            <aside
                ref={aside}
                inert={!open}
                className={cn(
                    'hidden shrink-0 flex-col overflow-hidden bg-sidebar md:flex',
                    open && 'border-l border-border-strong',
                    !dragging && 'transition-[width] duration-200',
                )}
                style={{ width: open ? width : 0 }}
            >
                {/* The content keeps the committed width while the box slides, so nothing
                    inside reflows on the way. */}
                <div className="flex min-h-0 flex-1 flex-col" style={{ minWidth: width }}>
                    {tabs.length === 0 ? (
                        <div className="flex min-h-0 flex-1 flex-col">
                            <div
                                data-shell-strip="top"
                                className="flex h-shell-top shrink-0 items-center gap-2 px-3"
                            >
                                <span className="text-xs font-semibold tracking-wide text-faint uppercase">
                                    {EMPTY_HEADING}
                                </span>
                            </div>
                            <p className="p-4 text-sm text-muted-foreground">{NOTHING_HERE}</p>
                        </div>
                    ) : (
                        <Tabs
                            value={active}
                            onValueChange={(value) => {
                                panelTab.set(String(value))
                            }}
                            className="flex min-h-0 flex-1 flex-col gap-0"
                        >
                            <div
                                data-shell-strip="top"
                                className="flex h-shell-top shrink-0 items-center gap-2 px-2"
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
                                <TabsContent
                                    key={tab.id}
                                    value={tab.id}
                                    className="min-h-0 flex-1 overflow-y-auto"
                                >
                                    {tab.render()}
                                </TabsContent>
                            ))}
                        </Tabs>
                    )}
                </div>
            </aside>
        </>
    )
}
