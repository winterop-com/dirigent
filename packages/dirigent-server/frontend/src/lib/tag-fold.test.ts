import { describe, expect, test } from 'vitest'

import { chipWidth, foldTags, TAGS_SHOWN } from '@/lib/tag-fold'

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
        const room = 240
        const fold = foldTags(FIFTEEN, room, 1)
        expect(lineWidth([...fold.shown, `+${String(fold.folded.length)}`])).toBeLessThanOrEqual(room)
        expect(fold.shown.length + fold.folded.length).toBe(FIFTEEN.length)
        // A narrow column folds hard: the words go behind one chip.
        expect(fold.folded.length).toBeGreaterThanOrEqual(10)
    })

    test('a wider column draws more of them', () => {
        const narrow = foldTags(FIFTEEN, 240, 1)
        const wide = foldTags(FIFTEEN, 480, 1)
        expect(wide.shown.length).toBeGreaterThan(narrow.shown.length)
    })

    test('never more than the cap, however much room there is', () => {
        const fold = foldTags(FIFTEEN, 4000, 2)
        expect(fold.shown).toHaveLength(TAGS_SHOWN)
        expect(fold.folded).toHaveLength(FIFTEEN.length - TAGS_SHOWN)
    })

    test('a column narrower than one chip still says what the row is filed under', () => {
        const fold = foldTags(FIFTEEN, 10, 1)
        expect(fold.shown).toHaveLength(1)
        expect(fold.folded).toHaveLength(FIFTEEN.length - 1)
    })

    test('a row with no room measured yet draws what it would draw at the cap', () => {
        const fold = foldTags(FIFTEEN, 0, 1)
        expect(fold.shown).toHaveLength(TAGS_SHOWN)
    })
})
