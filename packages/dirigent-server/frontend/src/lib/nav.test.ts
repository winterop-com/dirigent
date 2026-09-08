import { describe, expect, test } from 'vitest'

import { DASHBOARD_PATH, NAV, entriesFor, entryAt, marksOnlyItself, sectionsFor } from '@/lib/nav'

describe('the navigation', () => {
    test('sends a reader with no address of their own to a screen that exists', () => {
        expect(entriesFor('admin').map((entry) => entry.path)).toContain(DASHBOARD_PATH)
    })

    // REVERT-PROOF. Point the root at a listing again and this fails: the front door answers how
    // the instance is doing, which is the question somebody with no address of their own is
    // asking, and no screen named after a noun answers it.
    test('is the root itself, not one of the nouns', () => {
        expect(DASHBOARD_PATH).toBe('/')
    })

    test('offers the front door to every account, admin or not', () => {
        expect(entriesFor('operator').map((entry) => entry.path)).toContain(DASHBOARD_PATH)
    })

    test('leads with it, because it is what a reader lands on', () => {
        expect(entriesFor(null)[0].path).toBe(DASHBOARD_PATH)
    })

    test('every path is absolute, because the router table spells them that way', () => {
        for (const entry of NAV.flatMap((section) => section.entries)) {
            expect(entry.path.startsWith('/')).toBe(true)
        }
    })

    test('names no screen twice', () => {
        const paths = NAV.flatMap((section) => section.entries).map((entry) => entry.path)
        expect(new Set(paths).size).toBe(paths.length)
    })
})

describe('the line the palette carries beside every row', () => {
    test('every entry has one, because every entry is a row the palette offers', () => {
        for (const entry of NAV.flatMap((section) => section.entries)) {
            expect(entry.hint.length).toBeGreaterThan(0)
        }
    })

    test('is a fragment rather than a sentence: it is read beside a row, not as prose', () => {
        for (const entry of NAV.flatMap((section) => section.entries)) {
            expect(entry.hint.endsWith('.')).toBe(false)
        }
    })

    test('fits a palette row, which has a title on the same line as it', () => {
        for (const entry of NAV.flatMap((section) => section.entries)) {
            expect(entry.hint.length).toBeLessThanOrEqual(48)
        }
    })

    test('says something different about every screen', () => {
        const hints = NAV.flatMap((section) => section.entries).map((entry) => entry.hint)
        expect(new Set(hints).size).toBe(hints.length)
    })

    test('does not merely repeat the label it sits under', () => {
        for (const entry of NAV.flatMap((section) => section.entries)) {
            expect(entry.hint.toLowerCase()).not.toBe(entry.label.toLowerCase())
        }
    })
})

describe('role gating', () => {
    test('offers the admin section to an admin', () => {
        expect(sectionsFor('admin').map((section) => section.id)).toContain('admin')
    })

    test('withholds it from every other role', () => {
        expect(sectionsFor('operator').map((section) => section.id)).not.toContain('admin')
        expect(sectionsFor('viewer').map((section) => section.id)).not.toContain('admin')
    })

    test('draws the ungated sections before the identity is known, rather than nothing at all', () => {
        expect(sectionsFor(null).map((section) => section.id)).toEqual(['operate'])
    })
})

describe('which entry an address is inside', () => {
    test('is the entry itself for its own address', () => {
        expect(entryAt('/runs')?.label).toBe('Runs')
    })

    test('is the section for an address below it, so a detail screen still marks its section', () => {
        expect(entryAt('/runs/6f1f6b0e-4c1e-4d0a-9d9c-2f2f9b7f7a11')?.label).toBe('Runs')
    })

    test('is the longest match, so /admin/users marks Users rather than the admin overview', () => {
        expect(entryAt('/admin/users')?.label).toBe('Users')
        expect(entryAt('/admin')?.label).toBe('Overview')
    })

    test('is nothing for an address this app does not answer', () => {
        expect(entryAt('/nowhere')).toBeNull()
    })

    test('is the front door for the root and for nothing below it', () => {
        expect(entryAt('/')?.label).toBe('Dashboard')
        expect(entryAt('/runs')?.label).toBe('Runs')
    })
})

describe('which addresses mark an entry', () => {
    test('the root is marked at the root alone, because every address is under it', () => {
        expect(marksOnlyItself('/')).toBe(true)
    })

    test('the admin overview is marked at its own address, because three screens sit below it', () => {
        expect(marksOnlyItself('/admin')).toBe(true)
    })

    // REVERT-PROOF. A screen with nothing beneath it stays marked while a detail screen of its
    // own is open: a run being read is still the reader being in Runs.
    test('a screen with nothing below it is marked by everything under it too', () => {
        expect(marksOnlyItself('/runs')).toBe(false)
        expect(marksOnlyItself('/pipelines')).toBe(false)
    })
})
