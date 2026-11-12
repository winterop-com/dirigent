import { beforeEach, describe, expect, test } from 'vitest'

import {
    forgetPlacements,
    heldLayout,
    holdPlacement,
    keepPlacements,
    layoutKey,
    loadPlacements,
    placeStep,
    readPlacements,
    writePlacements,
} from '@/lib/canvas-layout'

/**
 * Storage is a browser's, and these tests run in Node, so the whole of what this module needs of
 * it is stood up here: four methods over a map. What is under test is what is written and what
 * comes back, which is exactly what a reload does.
 */
function stubStorage(): Map<string, string> {
    const held = new Map<string, string>()
    const storage = {
        getItem: (key: string) => held.get(key) ?? null,
        setItem: (key: string, value: string) => {
            held.set(key, value)
        },
        removeItem: (key: string) => {
            held.delete(key)
        },
        clear: () => {
            held.clear()
        },
        key: (index: number) => [...held.keys()][index] ?? null,
        get length() {
            return held.size
        },
    }
    Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true, writable: true })
    return held
}

/** What elk placed, before anybody moved anything. */
let stored: Map<string, string>

beforeEach(() => {
    stored = stubStorage()
    heldLayout.set({ pipeline: null, placements: {} })
})

describe('where a pipeline arrangement is kept', () => {
    test('is one key of its own, named for the pipeline', () => {
        expect(layoutKey('std-convert-fan-out')).toBe('dirigent.layout.std-convert-fan-out')
    })

    test('is nothing at all for a pipeline nobody has arranged', () => {
        expect(readPlacements('untouched')).toEqual({})
    })

    test('is the pixels a box was dropped at, and they come back as they went in', () => {
        writePlacements('chain', { fetch: { x: 120.5, y: -40 } })
        expect(readPlacements('chain')).toEqual({ fetch: { x: 120.5, y: -40 } })
    })

    test('is dropped rather than drawn when what is stored is not a position', () => {
        stored.set(layoutKey('junk'), '{"fetch":{"x":"left","y":3},"report":{"x":1,"y":2},"nope":null}')
        expect(readPlacements('junk')).toEqual({ report: { x: 1, y: 2 } })
    })

    test('is dropped rather than refused when what is stored is not JSON at all', () => {
        stored.set(layoutKey('junk'), 'not json')
        expect(readPlacements('junk')).toEqual({})
    })
})

describe('the arrangement in front of somebody', () => {
    test('is read out of storage when its pipeline is opened', () => {
        writePlacements('chain', { fetch: { x: 10, y: 20 } })
        loadPlacements('chain')
        expect(heldLayout.get()).toEqual({ pipeline: 'chain', placements: { fetch: { x: 10, y: 20 } } })
    })

    test('follows a drag without writing, and is written when the drag ends', () => {
        loadPlacements('chain')
        holdPlacement('fetch', { x: 5, y: 5 })
        expect(readPlacements('chain')).toEqual({})
        keepPlacements()
        expect(readPlacements('chain')).toEqual({ fetch: { x: 5, y: 5 } })
    })

    test('takes a step put somewhere on purpose and keeps it there', () => {
        loadPlacements('chain')
        placeStep('added', { x: 42, y: 7 })
        expect(readPlacements('chain')).toEqual({ added: { x: 42, y: 7 } })
    })

    test('is given back to elk by a re-layout, here and in storage', () => {
        writePlacements('chain', { fetch: { x: 10, y: 20 } })
        loadPlacements('chain')
        forgetPlacements()
        expect(heldLayout.get().placements).toEqual({})
        expect(readPlacements('chain')).toEqual({})
        expect(stored.has(layoutKey('chain'))).toBe(false)
    })

    test('belongs to one pipeline, so opening another starts from whatever that one holds', () => {
        writePlacements('chain', { fetch: { x: 10, y: 20 } })
        loadPlacements('chain')
        loadPlacements('other')
        expect(heldLayout.get()).toEqual({ pipeline: 'other', placements: {} })
    })
})
