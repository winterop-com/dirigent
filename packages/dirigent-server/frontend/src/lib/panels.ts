/**
 * How the shell is laid out, and what survives a reload.
 *
 * PX-INTENT. The right panel's width is kept in pixels, not as a fraction of the window,
 * because what somebody dragged it to was a decision about the content in it -- "wide enough
 * for a log line", "narrow enough to leave the table readable" -- and a fraction re-decides
 * that every time the window is resized. A window narrower than the stored width clamps for
 * that session and leaves the stored number alone, so the intent comes back with the window.
 *
 * Small facts, one module store each, each read straight out of storage as it is built so
 * the shell renders at its settled size on the first paint rather than snapping into place.
 */

import type { ReactNode } from 'react'

import { createStore } from '@winterop-com/sokkel-ui/lib/stored'

import type { Icon } from '@/lib/icons'
import '@/lib/stored-prefix'

/** The rail's width when nobody has dragged it: its longest word, and room either side of it. */
export const RAIL_WIDTH = 168

/** Narrower than this and the rail's longest word no longer fits, so a drag stops here. */
export const RAIL_MIN_WIDTH = 152

/** Wider than this and the rail is taking the screen's room for nothing it can show. */
export const RAIL_MAX_WIDTH = 320

/** Where the right panel opens when nobody has dragged it yet. */
export const PANEL_DEFAULT_WIDTH = 360

/** Narrower than this is not a panel, it is a sliver, so a drag stops here. */
export const PANEL_MIN_WIDTH = 240

/** Wider than this and the screen the panel is beside stops being the screen. */
export const PANEL_MAX_WIDTH = 720

/** Hold a dragged width inside what the shell can actually draw. */
export function clampPanelWidth(width: number): number {
    return Math.min(PANEL_MAX_WIDTH, Math.max(PANEL_MIN_WIDTH, Math.round(width)))
}

/** Hold a dragged rail width between what its words need and what the screen can spare. */
export function clampRailWidth(width: number): number {
    return Math.min(RAIL_MAX_WIDTH, Math.max(RAIL_MIN_WIDTH, Math.round(width)))
}

const isFlag = (value: unknown) => typeof value === 'boolean'
const isWidth = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value > 0

/** Whether the rail is taken off screen, which is the reader's and is kept. */
export const railHidden = createStore(false, { key: 'railHidden', check: isFlag })

/** The rail's width in pixels, which the reader drags and which is kept. */
export const railWidth = createStore(RAIL_WIDTH, {
    key: 'railWidth',
    check: isWidth,
    normalize: clampRailWidth,
})

/** Set the rail's width, in pixels, clamped to what it can draw, and keep it. */
export function setRailWidth(width: number): void {
    railWidth.set(clampRailWidth(width))
}

/** Whether the rail is narrowed to its marks, which is the reader's and is kept. */
export const railCollapsed = createStore(false, { key: 'railCollapsed', check: isFlag })

/** Narrow the rail to its marks, or widen it again, and keep that. */
export function setRailCollapsed(collapsed: boolean): void {
    railCollapsed.set(collapsed)
}

/**
 * Whether the right panel is drawn open.
 *
 * TWO FACTS, ONE STORED. What the reader chose with the toggle is their preference, and it is
 * the only thing written to storage. A screen opening the panel -- a selection, a link that
 * names a row -- opens it for that visit alone: the next screen starts from the preference.
 */
const panelPreferred = createStore(false, { key: 'panelOpen', check: isFlag })

export const panelOpen = createStore(panelPreferred.get())

/** An open asked for by a screen that has not filled the panel since. */
let visitOpenPending = false
export const panelWidth = createStore(PANEL_DEFAULT_WIDTH, {
    key: 'panelWidth',
    check: isWidth,
    normalize: clampPanelWidth,
})

/** Take the navigation rail off screen, or bring it back. */
export function toggleRail(): void {
    railHidden.update((hidden) => !hidden)
}

/**
 * Whether the panel is standing as a sheet, which is what it is below the breakpoint.
 *
 * NOT PERSISTED, unlike the panel's own open flag. A sheet covers the screen, and a session
 * that opened one on a phone yesterday must not begin behind it today.
 */
export const panelSheet = createStore(false)

/**
 * Open the right panel for this visit to the screen, which is what selecting something does.
 *
 * It writes no preference: a deep link or a selection is not the reader choosing how the
 * panel stands on every screen.
 */
export function openPanel(): void {
    panelSheet.set(true)
    visitOpenPending = true
    panelOpen.set(true)
}

/**
 * Take back the open a row asked for, which is what unchoosing that row does.
 *
 * The mirror of `openPanel`, and it leaves the reader's preference alone for the same reason:
 * the sheet comes down, and on a wide window the screen's own unfilling is what takes the panel
 * away, because a panel nobody has filled is not drawn.
 */
export function closePanel(): void {
    visitOpenPending = false
    panelSheet.set(false)
}

/**
 * Whether the panel is on screen right now, which is not the same as whether it is open.
 *
 * Below the breakpoint what is beside a screen is under it, and `panelSheet` is what says so;
 * above it the panel's own flag does. `openPanel` sets both, so neither alone answers for both
 * widths -- and a row pressed while nothing is standing opens the panel rather than closing a
 * selection nothing is showing.
 */
export function panelStanding(small: boolean): boolean {
    return small ? panelSheet.get() : panelOpen.get()
}

/** Show or hide the right panel, and keep that as the reader's preference. */
export function togglePanel(): void {
    const open = !panelOpen.get()
    visitOpenPending = false
    panelPreferred.set(open)
    panelOpen.set(open)
}

/** Set the right panel's width, in pixels, clamped to what the shell can draw. */
export function setPanelWidth(width: number): void {
    panelWidth.set(clampPanelWidth(width))
}

/**
 * One tab in the right panel.
 *
 * `render` rather than an element, so a screen's panel is built when the panel is drawn instead
 * of on every render of the screen behind it.
 */
export interface PanelTab {
    /** Stable across rebuilds of the list: it is what the open tab is remembered by. */
    id: string
    label: string
    /** Drawn over the label in the tab strip along the foot below the breakpoint. */
    icon?: Icon
    render: () => ReactNode
}

/** What the right panel currently shows, or nothing on a screen that fills no panel. */
export const panelTabs = createStore<readonly PanelTab[]>([])

/**
 * Which tab is open, held by id rather than by position.
 *
 * A screen that gains a tab must not move the reader onto a different one, and an id no
 * current screen offers falls back to the first tab rather than showing nothing.
 */
export const panelTab = createStore<string | null>(null)

/**
 * Open the panel on one named tab.
 *
 * This is what a screen calls when a click somewhere else is a request to read a particular
 * thing -- a log line's step prefix asking for that step. `openPanel` on its own leaves
 * whichever tab was last open in front of somebody, which answers a question they did not ask.
 */
export function openPanelTab(id: string): void {
    panelTab.set(id)
    openPanel()
}

/**
 * Fill the right panel until the returned function is called.
 *
 * A screen calls this from an effect and returns the result, the way it registers palette
 * actions, so a panel cannot outlive the screen whose data it is drawing. The last screen to
 * call it owns the panel: two screens are never mounted at once.
 */
export function fillPanel(tabs: readonly PanelTab[], owner?: PanelOwner): () => void {
    panelTabs.set(tabs)
    if (owner !== undefined && owner.screen !== lastScreen) {
        lastScreen = owner.screen
        panelTab.set(owner.open ?? tabs[0]?.id ?? null)
        // An open this screen asked for before its first fill is its own; any other is the
        // last screen's, so this one starts from the reader's preference and the sheet the
        // last screen raised comes down rather than being carried across.
        if (!visitOpenPending) {
            panelSheet.set(false)
            panelOpen.set(owner.shut === true ? false : panelPreferred.get())
        }
    }
    if (owner !== undefined) visitOpenPending = false
    return () => {
        if (panelTabs.get() === tabs) panelTabs.set([])
    }
}

/**
 * Which screen a fill belongs to, and where that screen starts.
 *
 * A SCREEN OWNS ITS PANEL. The open-tab id is global so it survives a screen's own re-fills,
 * but it must not survive a change of screen: the listing's preview tab following somebody
 * into the editor answers a question they did not ask. A fill that names its screen resets
 * the open tab to that screen's own default the first time the screen fills.
 */
export interface PanelOwner {
    /** Stable per screen instance: 'pipelines', or 'editor:one-code'. */
    screen: string
    /** The tab this screen starts on; the first tab when unsaid. */
    open?: string
    /** A screen whose panel is reference beside the work starts with it shut, whatever was preferred. */
    shut?: boolean
}

let lastScreen: string | null = null
