import { afterAll, beforeAll, describe, expect, test } from 'vitest'

import {
    PANEL_MAX_WIDTH,
    PANEL_MIN_WIDTH,
    RAIL_MAX_WIDTH,
    RAIL_MIN_WIDTH,
    clampPanelWidth,
    clampRailWidth,
    fillPanel,
    openPanel,
    openPanelTab,
    panelOpen,
    panelTab,
    panelTabs,
    railWidth,
    setRailWidth,
    togglePanel,
    type PanelTab,
} from '@/lib/panels'

describe('the right panel width', () => {
    test('is kept as the pixels somebody dragged it to', () => {
        expect(clampPanelWidth(413)).toBe(413)
    })

    test('rounds to whole pixels, because a pointer reports fractions and a layout does not', () => {
        expect(clampPanelWidth(412.6)).toBe(413)
    })

    test('stops at a width that is still a panel rather than a sliver', () => {
        expect(clampPanelWidth(40)).toBe(PANEL_MIN_WIDTH)
    })

    test('stops before the panel becomes the screen it sits beside', () => {
        expect(clampPanelWidth(4000)).toBe(PANEL_MAX_WIDTH)
    })
})

describe('what the right panel is showing', () => {
    test('is nothing until a screen fills it', () => {
        expect(panelTabs.get()).toEqual([])
    })

    test('is the tabs the screen in front of it registered', () => {
        const tabs: PanelTab[] = [{ id: 'step', label: 'Step', render: () => null }]
        fillPanel(tabs)
        expect(panelTabs.get()).toBe(tabs)
    })

    test('is empty again once that screen unmounts', () => {
        const stop = fillPanel([{ id: 'run', label: 'Run', render: () => null }])
        stop()
        expect(panelTabs.get()).toEqual([])
    })

    test('leaves the panel alone when a later screen already claimed it', () => {
        // Unmount order is React's, not the screens': a stale teardown must not empty the panel
        // the screen after it just filled.
        const stopFirst = fillPanel([{ id: 'a', label: 'A', render: () => null }])
        const second: PanelTab[] = [{ id: 'b', label: 'B', render: () => null }]
        fillPanel(second)
        stopFirst()
        expect(panelTabs.get()).toBe(second)
    })
})

describe('which panel tab is open', () => {
    test("is nobody's choice until something makes one", () => {
        panelTab.set(null)
        expect(panelTab.get()).toBeNull()
    })

    test('is named by a screen sending a reader to one particular tab', () => {
        // A log line's step prefix is asking for that step, not for whichever tab was last open.
        panelTab.set('run')
        openPanelTab('step')
        expect(panelTab.get()).toBe('step')
    })

    test('opens the panel along with it, because a named tab nobody can see is not open', () => {
        panelOpen.set(false)
        openPanelTab('step')
        expect(panelOpen.get()).toBe(true)
    })
})

describe('whether the panel is open', () => {
    const tabs: PanelTab[] = [{ id: 'one', label: 'One', render: () => null }]
    // Tests run in Node, so storage is two methods over a map.
    const held = new Map<string, string>()
    const stored = () => held.get('dirigent.panelOpen') ?? null

    beforeAll(() => {
        Object.defineProperty(globalThis, 'localStorage', {
            value: {
                getItem: (key: string) => held.get(key) ?? null,
                setItem: (key: string, value: string) => held.set(key, value),
            },
            configurable: true,
            writable: true,
        })
    })

    afterAll(() => {
        Reflect.deleteProperty(globalThis, 'localStorage')
    })

    function preferClosed() {
        if (panelOpen.get()) togglePanel()
        else {
            togglePanel()
            togglePanel()
        }
    }

    test("is the reader's to keep when they toggle it", () => {
        preferClosed()
        expect(stored()).toBe('false')
        togglePanel()
        expect(panelOpen.get()).toBe(true)
        expect(stored()).toBe('true')
    })

    test('opens for a screen that asks without writing a preference', () => {
        preferClosed()
        openPanel()
        expect(panelOpen.get()).toBe(true)
        expect(stored()).toBe('false')
    })

    test('stays open on the screen that asked before its first fill', () => {
        preferClosed()
        fillPanel(tabs, { screen: 'panel-test:before' })
        openPanel()
        fillPanel(tabs, { screen: 'panel-test:linked' })
        expect(panelOpen.get()).toBe(true)
    })

    test("goes back to the reader's preference on the next screen", () => {
        preferClosed()
        fillPanel(tabs, { screen: 'panel-test:linked' })
        openPanel()
        fillPanel(tabs, { screen: 'panel-test:linked' })
        fillPanel(tabs, { screen: 'panel-test:editor' })
        expect(panelOpen.get()).toBe(false)
    })

    test('keeps an open the reader chose across screens', () => {
        preferClosed()
        togglePanel()
        fillPanel(tabs, { screen: 'panel-test:a' })
        fillPanel(tabs, { screen: 'panel-test:b' })
        expect(panelOpen.get()).toBe(true)
    })
})

describe('the rail width', () => {
    test('clamps a drag to what the labels need and the screen affords', () => {
        expect(clampRailWidth(20)).toBe(RAIL_MIN_WIDTH)
        expect(clampRailWidth(9000)).toBe(RAIL_MAX_WIDTH)
        expect(clampRailWidth(228.6)).toBe(229)
    })

    test('keeps the dragged width and clamps what it stores', () => {
        setRailWidth(500)
        expect(railWidth.get()).toBe(RAIL_MAX_WIDTH)
        setRailWidth(240)
        expect(railWidth.get()).toBe(240)
    })
})
