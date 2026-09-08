import { describe, expect, it } from 'vitest'

import {
    WINDOW_BACKWARDS,
    WINDOW_HALF,
    WINDOW_NEEDED,
    readWindow,
    referencesWindow,
    windowBox,
    windowInstant,
} from '@/lib/run-window'

/** A document whose window reference is a nested config string, which is where they are written. */
const READS_WINDOW = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'gdacs-disaster-updates',
    steps: {
        dates: {
            block: 'transform.jq',
            config: {
                program: '.',
                values: { from: '${run.window.start}', to: '${run.window.end}' },
            },
        },
    },
}

/** The same shape with no reference in it, which is every pipeline started by hand. */
const READS_NONE = {
    format: 'dirigent/v1',
    kind: 'pipeline',
    code: 'params-showcase',
    steps: {
        fetch: {
            block: 'http.request',
            config: { method: 'GET', url: 'https://example.test/${params.day}' },
        },
    },
}

describe('whether a document needs a window', () => {
    it('finds the reference wherever in the document it is written', () => {
        expect(referencesWindow(READS_WINDOW)).toBe(true)
    })

    it('says a document that reads no window needs none', () => {
        expect(referencesWindow(READS_NONE)).toBe(false)
        expect(referencesWindow(null)).toBe(false)
    })

    it('finds one written inside a list', () => {
        expect(referencesWindow({ steps: { fan: { config: { items: ['${run.window.start}'] } } } })).toBe(true)
    })
})

describe('a box of wall clock, and the instant it stands for', () => {
    it('writes the zone the app is reading clocks against onto it', () => {
        expect(windowInstant('2026-09-03T00:00', 0)).toBe('2026-09-03T00:00:00Z')
        expect(windowInstant('2026-09-03T00:00', 120)).toBe('2026-09-03T00:00:00+02:00')
        expect(windowInstant('2026-09-03T00:00', -330)).toBe('2026-09-03T00:00:00-05:30')
    })

    it('reads an empty or half-typed box as no instant at all', () => {
        expect(windowInstant('', 0)).toBeNull()
        expect(windowInstant('2026-09-03', 0)).toBeNull()
    })

    it('reads one instant off the wire back onto the same clock', () => {
        expect(windowBox('2026-09-03T00:00:00Z', 0)).toBe('2026-09-03T00:00')
        expect(windowBox('2026-09-03T00:00:00Z', 120)).toBe('2026-09-03T02:00')
        expect(windowBox(null, 0)).toBe('')
        expect(windowBox('not an instant', 0)).toBe('')
    })
})

/** The clock the app is set to in these readings, which is what the UTC setting is. */
const UTC = () => 0

describe('what the two boxes amount to', () => {
    it('sends both ends when both are given and the window runs forwards', () => {
        expect(readWindow('2026-09-03T00:00', '2026-09-04T00:00', false, UTC)).toEqual({
            kind: 'window',
            window: { window_start: '2026-09-03T00:00:00Z', window_end: '2026-09-04T00:00:00Z' },
        })
    })

    it('sends neither field where a document that needs no window was given none', () => {
        expect(readWindow('', '', false, UTC)).toEqual({ kind: 'none' })
    })

    it('shuts the run on a document that reads a window and was given none', () => {
        expect(readWindow('', '', true, UTC)).toEqual({ kind: 'unready', why: WINDOW_NEEDED })
    })

    it('shuts the run on one end without the other', () => {
        expect(readWindow('2026-09-03T00:00', '', false, UTC)).toEqual({ kind: 'unready', why: WINDOW_HALF })
        expect(readWindow('2026-09-03T00:00', '', true, UTC)).toEqual({ kind: 'unready', why: WINDOW_NEEDED })
    })

    it('shuts the run on a window that does not run forwards', () => {
        expect(readWindow('2026-09-04T00:00', '2026-09-03T00:00', false, UTC)).toEqual({
            kind: 'unready',
            why: WINDOW_BACKWARDS,
        })
        expect(readWindow('2026-09-03T00:00', '2026-09-03T00:00', true, UTC)).toEqual({
            kind: 'unready',
            why: WINDOW_NEEDED,
        })
    })
})
