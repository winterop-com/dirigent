import { describe, expect, it } from 'vitest'

import { folded, type Held } from '@/hooks/use-paged'
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
