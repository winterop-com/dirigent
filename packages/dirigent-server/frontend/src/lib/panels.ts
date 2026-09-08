/**
 * How the shell is laid out, and what survives a reload.
 *
 * PX-INTENT. The right panel's width is kept in pixels, not as a fraction of the window,
 * because what somebody dragged it to was a decision about the content in it -- "wide enough
 * for a log line", "narrow enough to leave the table readable" -- and a fraction re-decides
 * that every time the window is resized. A window narrower than the stored width clamps for
 * that session and leaves the stored number alone, so the intent comes back with the window.
 *
 * Three small facts, three module stores, each read straight out of storage as it is built so
 * the shell renders at its settled size on the first paint rather than snapping into place.
 */

import type { ReactNode } from 'react'

import { createStore } from '@/lib/store'

/** The rail's width when it shows labels and nobody has dragged it. */
export const RAIL_WIDTH = 240

/** Narrower and the labels it exists to show start truncating. */
export const RAIL_MIN_WIDTH = 160

/** Wider is dead space: the longest label fits long before this. */
export const RAIL_MAX_WIDTH = 320

/** Its width when collapsed: icons, and the room for a focus ring around them. */
export const RAIL_COLLAPSED_WIDTH = 56

/** Where the right panel opens when nobody has dragged it yet. */
export const PANEL_DEFAULT_WIDTH = 360

/** Narrower than this is not a panel, it is a sliver, so a drag stops here. */
export const PANEL_MIN_WIDTH = 240

/** Wider than this and the screen the panel is beside stops being the screen. */
export const PANEL_MAX_WIDTH = 720

const RAIL_KEY = 'dirigent.railCollapsed'
const RAIL_WIDTH_KEY = 'dirigent.railWidth'
const PANEL_OPEN_KEY = 'dirigent.panelOpen'
const PANEL_WIDTH_KEY = 'dirigent.panelWidth'

function readFlag(key: string, fallback: boolean): boolean {
    try {
        const stored = localStorage.getItem(key)
        return stored === null ? fallback : stored === 'true'
    } catch {
        return fallback
    }
}

function readWidth(key: string, fallback: number, clamp: (width: number) => number): number {
    try {
        const stored = Number(localStorage.getItem(key))
        return Number.isFinite(stored) && stored > 0 ? clamp(stored) : fallback
    } catch {
        return fallback
    }
}

function write(key: string, value: string): void {
    try {
        localStorage.setItem(key, value)
    } catch {
        // Storage denied: the layout holds for as long as this document is open.
    }
}

/** Hold a dragged width inside what the shell can actually draw. */
export function clampPanelWidth(width: number): number {
    return Math.min(PANEL_MAX_WIDTH, Math.max(PANEL_MIN_WIDTH, Math.round(width)))
}

/** Hold a dragged rail width between the labels' needs and the screen's. */
export function clampRailWidth(width: number): number {
    return Math.min(RAIL_MAX_WIDTH, Math.max(RAIL_MIN_WIDTH, Math.round(width)))
}

export const railCollapsed = createStore(readFlag(RAIL_KEY, false))
export const panelOpen = createStore(readFlag(PANEL_OPEN_KEY, false))
export const panelWidth = createStore(readWidth(PANEL_WIDTH_KEY, PANEL_DEFAULT_WIDTH, clampPanelWidth))
export const railWidth = createStore(readWidth(RAIL_WIDTH_KEY, RAIL_WIDTH, clampRailWidth))

/**
 * Whether the rail's edge is being dragged right now.
 *
 * Everything that follows the rail's width -- the status bar's settings cell as much as the
 * rail itself -- animates a committed width and follows a dragged one raw: a transition
 * chasing a hand makes the edge rubber-band behind it.
 */
export const railDragging = createStore(false)

/** Collapse or expand the navigation rail. */
export function toggleRail(): void {
    railCollapsed.update((collapsed) => {
        write(RAIL_KEY, String(!collapsed))
        return !collapsed
    })
}

/**
 * Whether the panel is standing as a sheet, which is what it is below the breakpoint.
 *
 * NOT PERSISTED, unlike the panel's own open flag. A sheet covers the screen, and a session
 * that opened one on a phone yesterday must not begin behind it today.
 */
export const panelSheet = createStore(false)

/** Take the sheet down, leaving the panel's own open flag where it was. */
export function closeSheet(): void {
    panelSheet.set(false)
}

/** Open the right panel, which is what selecting something on a screen does. */
export function openPanel(): void {
    panelSheet.set(true)
    if (panelOpen.get()) return
    write(PANEL_OPEN_KEY, 'true')
    panelOpen.set(true)
}

/** Show or hide the right panel. */
export function togglePanel(): void {
    panelOpen.update((open) => {
        write(PANEL_OPEN_KEY, String(!open))
        return !open
    })
}

/** Set the right panel's width, in pixels, clamped to what the shell can draw. */
export function setRailWidth(width: number): void {
    const clamped = clampRailWidth(width)
    railWidth.set(clamped)
    write(RAIL_WIDTH_KEY, String(clamped))
}

export function setPanelWidth(width: number): void {
    const clamped = clampPanelWidth(width)
    write(PANEL_WIDTH_KEY, String(clamped))
    panelWidth.set(clamped)
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
        // A sheet is over the screen it was raised from, so arriving at another one takes it
        // down rather than carrying it across.
        panelSheet.set(false)
    }
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
}

let lastScreen: string | null = null
