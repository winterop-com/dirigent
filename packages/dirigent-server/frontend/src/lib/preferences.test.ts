import { afterEach, describe, expect, test, vi } from 'vitest'

/**
 * Storage is a browser's, and these tests run in Node, so the whole of what this module needs of
 * it is stood up here: two methods over a map. A store here is built as the module is imported,
 * which is what a reload does, so every test imports it again against the storage it stood up.
 */
function stubStorage(held: Map<string, string> = new Map()): Map<string, string> {
    const storage = {
        getItem: (key: string) => held.get(key) ?? null,
        setItem: (key: string, value: string) => {
            held.set(key, value)
        },
    }
    Object.defineProperty(globalThis, 'localStorage', { value: storage, configurable: true, writable: true })
    return held
}

function refuse(): never {
    throw new Error('storage is denied')
}

/** A browser that refuses storage, which is a private window or a reader who blocked it. */
function denyStorage(): void {
    Object.defineProperty(globalThis, 'localStorage', {
        value: { getItem: refuse, setItem: refuse },
        configurable: true,
        writable: true,
    })
}

async function reload(): Promise<typeof import('@/lib/preferences')> {
    vi.resetModules()
    return import('@/lib/preferences')
}

afterEach(() => {
    Reflect.deleteProperty(globalThis, 'localStorage')
})

describe('the current-line preference', () => {
    test('is kept under a key of its own', async () => {
        stubStorage()
        const { HIGHLIGHT_LINE_KEY } = await reload()
        expect(HIGHLIGHT_LINE_KEY).toBe('dirigent.highlightLine')
    })

    test('is off for a reader who has never asked for it', async () => {
        stubStorage()
        const { DEFAULT_HIGHLIGHT_LINE, highlightLine } = await reload()
        expect(DEFAULT_HIGHLIGHT_LINE).toBe(false)
        expect(highlightLine.get()).toBe(false)
    })

    test('comes back as it was left', async () => {
        stubStorage(new Map([['dirigent.highlightLine', 'true']]))
        const { highlightLine } = await reload()
        expect(highlightLine.get()).toBe(true)
    })

    test('is written through, so the next visit opens on it', async () => {
        const held = stubStorage()
        const { HIGHLIGHT_LINE_KEY, highlightLine, setHighlightLine } = await reload()
        setHighlightLine(true)
        expect(highlightLine.get()).toBe(true)
        expect(held.get(HIGHLIGHT_LINE_KEY)).toBe('true')
        setHighlightLine(false)
        expect(held.get(HIGHLIGHT_LINE_KEY)).toBe('false')
    })

    // An editor already on screen subscribes rather than remounting, so the change has to be
    // published to be seen at all.
    test('tells whoever is watching, once per change', async () => {
        stubStorage()
        const { highlightLine, setHighlightLine } = await reload()
        let told = 0
        const stop = highlightLine.subscribe(() => {
            told += 1
        })
        setHighlightLine(true)
        setHighlightLine(true)
        stop()
        expect(told).toBe(1)
    })

    test('holds for as long as the document is open when storage is denied', async () => {
        denyStorage()
        const { highlightLine, setHighlightLine } = await reload()
        expect(highlightLine.get()).toBe(false)
        setHighlightLine(true)
        expect(highlightLine.get()).toBe(true)
    })
})

describe('the log-following preference', () => {
    test('opens following the tail unless somebody said otherwise', async () => {
        stubStorage()
        const { DEFAULT_FOLLOW_TAILS, FOLLOW_TAILS_KEY, followTails } = await reload()
        expect(FOLLOW_TAILS_KEY).toBe('dirigent.followTails')
        expect(DEFAULT_FOLLOW_TAILS).toBe(true)
        expect(followTails.get()).toBe(true)
    })

    test('comes back as it was left', async () => {
        stubStorage(new Map([['dirigent.followTails', 'false']]))
        const { followTails } = await reload()
        expect(followTails.get()).toBe(false)
    })

    test('is written through', async () => {
        const held = stubStorage()
        const { FOLLOW_TAILS_KEY, setFollowTails } = await reload()
        setFollowTails(false)
        expect(held.get(FOLLOW_TAILS_KEY)).toBe('false')
    })
})
