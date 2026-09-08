import { describe, expect, test } from 'vitest'

import {
    FORM_COLUMN,
    PANE_MAX,
    PANE_MIN,
    clampPaneWidth,
    paneBounds,
} from '@/components/login/pane-width'

describe('the login pane width', () => {
    test('holds a chosen width between the pane bounds', () => {
        expect(clampPaneWidth(800, 1920)).toBe(800)
        expect(clampPaneWidth(PANE_MIN - 200, 1920)).toBe(PANE_MIN)
        expect(clampPaneWidth(PANE_MAX + 400, 2600)).toBe(PANE_MAX)
    })

    test('leaves the form column what it needs, however wide the choice was', () => {
        // A 1440 window has room for 914 of pane before the form loses its own width.
        expect(paneBounds(1440).max).toBe(1440 - FORM_COLUMN)
        expect(clampPaneWidth(1200, 1440)).toBe(1440 - FORM_COLUMN)
        // Past the ceiling the pane's own clamp already had, the ceiling wins instead.
        expect(paneBounds(2600).max).toBe(PANE_MAX)
    })

    test('keeps the floor in a window too narrow for both columns', () => {
        expect(paneBounds(900)).toEqual({ min: PANE_MIN, max: PANE_MIN })
        expect(clampPaneWidth(800, 900)).toBe(PANE_MIN)
        expect(clampPaneWidth(300, 900)).toBe(PANE_MIN)
    })

    test('answers whole pixels', () => {
        expect(clampPaneWidth(800.4, 1920)).toBe(800)
        expect(clampPaneWidth(800.6, 1920)).toBe(801)
    })
})
