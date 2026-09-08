import { describe, expect, it } from 'vitest'

import type { Page, Problem } from '@/lib/api'
import { appended, exhausted, noRows, noted, prepended, refused, rowsRead, started } from '@/lib/paging'

interface Row {
    id: string
}

interface Run {
    id: string
    status: string
}

const idOf = (row: Row) => row.id

const runId = (row: Run) => row.id

function page(ids: string[], next: string | null = null): Page<Row> {
    return { items: ids.map((id) => ({ id })), next }
}

const REFUSAL: Problem = { status: 500, title: 'Server Error', detail: 'no', problems: [], instance: '/runs' }

describe('a cursor-paged listing', () => {
    it('starts with nothing read and nothing to continue from', () => {
        const state = noRows<Row>()
        expect(state.rows).toEqual([])
        expect(state.read).toBe(false)
        expect(exhausted(state)).toBe(false)
    })

    it('appends the next page after the rows already held, and takes its cursor', () => {
        const first = appended(noRows<Row>(), page(['a', 'b'], 'b'), idOf)
        const second = appended(started(first), page(['c', 'd'], 'd'), idOf)
        expect(second.rows.map(idOf)).toEqual(['a', 'b', 'c', 'd'])
        expect(second.next).toBe('d')
        expect(second.reading).toBe(false)
    })

    it('never holds one row twice, however the cursor lands', () => {
        const first = appended(noRows<Row>(), page(['a', 'b'], 'b'), idOf)
        const again = appended(first, page(['b', 'c'], 'c'), idOf)
        expect(again.rows.map(idOf)).toEqual(['a', 'b', 'c'])
    })

    it('is exhausted when a page carried no cursor, and not before', () => {
        const more = appended(noRows<Row>(), page(['a'], 'a'), idOf)
        expect(exhausted(more)).toBe(false)
        expect(exhausted(appended(more, page(['b']), idOf))).toBe(true)
    })

    it('puts what a recheck found at the head, and counts it', () => {
        const held = appended(noRows<Row>(), page(['b', 'c'], 'c'), idOf)
        const after = prepended(held, page(['a', 'b', 'c'], 'c'), idOf)
        expect(after.rows.map(idOf)).toEqual(['a', 'b', 'c'])
        expect(after.fresh).toBe(1)
    })

    it('adds nothing and counts nothing when a recheck finds what is already held', () => {
        const held = appended(noRows<Row>(), page(['a', 'b'], 'b'), idOf)
        const after = prepended(held, page(['a', 'b'], 'b'), idOf)
        expect(after.rows.map(idOf)).toEqual(['a', 'b'])
        expect(after.fresh).toBe(0)
    })

    it('refreshes a held row in place rather than moving it to the head', () => {
        const held = appended(noRows<Run>(), { items: [{ id: 'a', status: 'running' }], next: 'a' }, runId)
        const after = prepended(held, { items: [{ id: 'a', status: 'succeeded' }], next: 'a' }, runId)
        expect(after.rows).toEqual([{ id: 'a', status: 'succeeded' }])
        expect(after.fresh).toBe(0)
    })

    it('leaves the tail cursor alone when the head is re-read', () => {
        const held = appended(noRows<Row>(), page(['b'], 'b'), idOf)
        expect(prepended(held, page(['a', 'b'], 'somewhere else'), idOf).next).toBe('b')
    })

    it('forgets what arrived once the reader has been told', () => {
        const held = prepended(appended(noRows<Row>(), page(['b'], 'b'), idOf), page(['a', 'b'], 'b'), idOf)
        expect(held.fresh).toBe(1)
        const settled = noted(held)
        expect(settled.fresh).toBe(0)
        expect(noted(settled)).toBe(settled)
    })

    it('keeps the rows it has when a read is refused', () => {
        const held = appended(noRows<Row>(), page(['a'], 'a'), idOf)
        const after = refused(started(held), REFUSAL)
        expect(after.rows.map(idOf)).toEqual(['a'])
        expect(after.problem).toBe(REFUSAL)
        expect(after.reading).toBe(false)
    })
})

describe('the foot of a listing', () => {
    it('says there is more where the cursor says so', () => {
        expect(rowsRead(50, 'pipelines', true)).toBe('50 pipelines, more to load')
    })

    it('states the count alone once the listing has run out', () => {
        expect(rowsRead(50, 'pipelines', false)).toBe('50 pipelines')
    })

    it('counts one row in the singular', () => {
        expect(rowsRead(1, 'runs', false)).toBe('1 run')
        expect(rowsRead(0, 'runs', false)).toBe('0 runs')
    })
})
