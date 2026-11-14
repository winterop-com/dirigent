import { act, createElement, useEffect } from 'react'
import { createRoot, type Container } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { folded, usePaged, type Held, type Paging } from '@/hooks/use-paged'
import type { Page } from '@/lib/api'
import { appended, noRows, type Paged } from '@/lib/paging'

interface Row {
    id: string
}

const idOf = (row: Row) => row.id

const FIRST = { name: 'first' }
const SECOND = { name: 'second' }

function page(ids: string[], next: string | null = null) {
    return { items: ids.map((id) => ({ id })), next }
}

function heldFor(asked: unknown, ids: string[]): Held<Row> {
    return { asked, paged: appended(noRows<Row>(), page(ids, 'z'), idOf) }
}

const add = (ids: string[]) => (current: Paged<Row>) => appended(current, page(ids), idOf)

describe('folding an answer into what a screen holds', () => {
    it('folds an answer to the question being asked into the rows held for it', () => {
        const next = folded(heldFor(FIRST, ['a', 'b']), FIRST, FIRST, add(['c']))
        expect(next.asked).toBe(FIRST)
        expect(next.paged.rows.map(idOf)).toEqual(['a', 'b', 'c'])
    })

    it('leaves the rows and the question alone when the answer is to a question left behind', () => {
        const held = heldFor(SECOND, ['c'])
        const next = folded(held, FIRST, SECOND, add(['a', 'b']))
        expect(next).toBe(held)
    })

    it('leaves a listing that has not been read yet unread when a stale answer lands', () => {
        const held: Held<Row> = { asked: SECOND, paged: noRows<Row>() }
        expect(folded(held, FIRST, SECOND, add(['a'])).paged.read).toBe(false)
    })

    it('starts from empty rows when what is held answers another question', () => {
        const next = folded(heldFor(FIRST, ['a', 'b']), SECOND, SECOND, add(['c']))
        expect(next.asked).toBe(SECOND)
        expect(next.paged.rows.map(idOf)).toEqual(['c'])
    })
})

/**
 * A container React can mount a tree into without a DOM, for a tree that draws no elements: the
 * hooks run and their effects fire in React's own order, and nothing is ever put in the page.
 */
function bareContainer(): Container {
    const node = {
        nodeType: 1,
        nodeName: 'DIV',
        tagName: 'DIV',
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
    }
    return Object.assign(node, { ownerDocument: node }) as unknown as Container
}

/** What React DOM checks the focused element against before a commit; nothing here is one. */
class Frame {
    readonly frame = true
}

describe('a table asking for more as a page lands', () => {
    afterEach(() => {
        vi.unstubAllGlobals()
    })

    it('continues from the page that just landed, not the one held before it', async () => {
        const asked: (string | null)[] = []
        const pages: Record<string, Page<Row>> = {
            first: page(['a'], 'p2'),
            p2: page(['b']),
        }
        const read = (after: string | null) => {
            asked.push(after)
            return Promise.resolve(pages[after ?? 'first'])
        }

        // As a table does: its own effect asks for more once rows land and the cursor has more.
        function Table({ paging }: { paging: Paging<Row> }) {
            const { rows, next } = paging.state
            const { more } = paging
            useEffect(() => {
                if (rows.length > 0 && next !== null) more()
            }, [rows.length, next, more])
            return null
        }
        function Listing() {
            return createElement(Table, { paging: usePaged(read, idOf) })
        }

        vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
        vi.stubGlobal('window', { HTMLIFrameElement: Frame })
        const root = createRoot(bareContainer())
        await act(async () => {
            root.render(createElement(Listing))
        })
        await act(async () => {
            await Promise.resolve()
        })
        act(() => {
            root.unmount()
        })

        expect(asked).toEqual([null, 'p2'])
    })
})
