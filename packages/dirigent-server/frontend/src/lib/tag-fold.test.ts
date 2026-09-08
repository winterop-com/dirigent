import { describe, expect, test } from 'vitest'

import { chipWidth, foldTags, linesFor, roomFor, TAGS_SHOWN, WRAPS_AT } from '@/lib/tag-fold'

/** The fifteen words the fixture document files itself under. */
const FIFTEEN = [
    'gdacs',
    'disasters',
    'alerts',
    'humanitarian',
    'ingest',
    'hourly',
    'geo',
    'emergency',
    'feeds',
    'public',
    'climate',
    'reporting',
    'bulletin',
    'weekly',
    'joined',
]

/** How wide these chips are drawn on one line, gaps included. */
function lineWidth(words: readonly string[]): number {
    return words.reduce((total, word) => total + chipWidth(word), 0) + (words.length - 1) * 4
}

describe('what a row draws and what it folds', () => {
    test('a row with room for all of them folds nothing', () => {
        const fold = foldTags(['graph', 'transform'], 400, 1)
        expect(fold.shown).toEqual(['graph', 'transform'])
        expect(fold.folded).toEqual([])
    })

    test('what is drawn fits the room, and the fold is counted in it', () => {
        const room = roomFor(1050)
        const fold = foldTags(FIFTEEN, room, linesFor(1050))
        expect(lineWidth([...fold.shown, `+${String(fold.folded.length)}`])).toBeLessThanOrEqual(room)
        expect(fold.shown.length + fold.folded.length).toBe(FIFTEEN.length)
        // A narrow table folds hard: the identity keeps the width and the words go behind one chip.
        expect(fold.folded.length).toBeGreaterThanOrEqual(10)
    })

    test('a wider table draws more of them', () => {
        const narrow = foldTags(FIFTEEN, roomFor(1050), linesFor(1050))
        const wide = foldTags(FIFTEEN, roomFor(1440), linesFor(1440))
        expect(wide.shown.length).toBeGreaterThan(narrow.shown.length)
    })

    test('never more than the cap, however much room there is', () => {
        const fold = foldTags(FIFTEEN, 4000, 2)
        expect(fold.shown).toHaveLength(TAGS_SHOWN)
        expect(fold.folded).toHaveLength(FIFTEEN.length - TAGS_SHOWN)
    })

    test('one line under the wrapping width, two at it', () => {
        expect(linesFor(WRAPS_AT - 1)).toBe(1)
        expect(linesFor(WRAPS_AT)).toBe(2)
    })

    test('a table narrower than one chip still says what the row is filed under', () => {
        const fold = foldTags(FIFTEEN, 10, 1)
        expect(fold.shown).toHaveLength(1)
        expect(fold.folded).toHaveLength(FIFTEEN.length - 1)
    })

    test('a row with no room measured yet draws what it would draw at the cap', () => {
        const fold = foldTags(FIFTEEN, 0, 1)
        expect(fold.shown).toHaveLength(TAGS_SHOWN)
    })
})
