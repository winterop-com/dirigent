/**
 * A cursor-paged listing, as a screen holds one.
 *
 * NO PAGE NUMBERS, ANYWHERE. Every listing on this API is a keyset walk: a page carries its rows
 * and the opaque cursor the next page continues from, and there is no total to divide into pages.
 * So what a screen holds is the rows it has read and the cursor it would carry on from -- "load
 * more" appends, and a page whose `next` is null is the end of the listing.
 *
 * A REFRESH IS A PREPEND, NOT A RELOAD. A newest-first listing gains rows at the head, so
 * re-reading page one and putting what is new in front of what is held leaves the rows somebody
 * is already reading exactly where they were. Rows are matched by their own id: one that is
 * already held is replaced in place with the copy that just arrived, never added a second time.
 *
 * The transitions are pure functions over the state, so appending, deduping and running out are
 * decisions a Node test makes rather than a browser.
 */

import type { Page, Problem } from '@/lib/api'

/** How many rows a page of any listing in this app asks for. */
export const PAGE = 50

/** One listing, as far as it has been read. */
export interface Paged<T> {
    rows: T[]
    /** The cursor the next page continues from, or null at the end of the listing. */
    next: string | null
    /** Whether a read is in flight. */
    reading: boolean
    /** Whether the first page has landed, which is what tells an empty listing from an unread one. */
    read: boolean
    problem: Problem | null
    /** How many rows the last recheck found that were not already held. */
    fresh: number
}

/** A listing nothing has been read from yet. */
export function noRows<T>(): Paged<T> {
    return { rows: [], next: null, reading: true, read: false, problem: null, fresh: 0 }
}

/** A read has gone out. */
export function started<T>(state: Paged<T>): Paged<T> {
    return { ...state, reading: true, problem: null }
}

/** The next page landed: its rows go after the ones already held, and its cursor replaces theirs. */
export function appended<T>(state: Paged<T>, page: Page<T>, idOf: (row: T) => string): Paged<T> {
    const held = new Set(state.rows.map(idOf))
    const added = page.items.filter((row) => !held.has(idOf(row)))
    return {
        ...state,
        rows: [...state.rows, ...added],
        next: page.next,
        reading: false,
        read: true,
        problem: null,
        fresh: 0,
    }
}

/**
 * Page one was read again: what is new goes at the head, and what was already held is refreshed.
 *
 * The cursor is left alone. It names where the tail of what has been read continues from, and
 * re-reading the head says nothing about the tail.
 */
export function prepended<T>(state: Paged<T>, page: Page<T>, idOf: (row: T) => string): Paged<T> {
    const arrived = new Map(page.items.map((row) => [idOf(row), row]))
    const held = new Set(state.rows.map(idOf))
    const added = page.items.filter((row) => !held.has(idOf(row)))
    const refreshed = state.rows.map((row) => arrived.get(idOf(row)) ?? row)
    return { ...state, rows: [...added, ...refreshed], reading: false, read: true, problem: null, fresh: added.length }
}

/** The server refused. The rows already read stay; the refusal is what the screen shows. */
export function refused<T>(state: Paged<T>, problem: Problem | null): Paged<T> {
    return { ...state, reading: false, read: true, problem }
}

/** The reader has taken note of what arrived. */
export function noted<T>(state: Paged<T>): Paged<T> {
    return state.fresh === 0 ? state : { ...state, fresh: 0 }
}

/**
 * What the foot of a listing states: how many rows have been read, and whether there are more.
 *
 * A BARE COUNT READS AS A TOTAL. This API answers no total, so "50 pipelines" in front of an
 * instance holding 135 is a number somebody would act on and be wrong. The cursor is what says
 * there is more, and the foot says so beside the count.
 */
export function rowsRead(count: number, noun: string, more: boolean): string {
    const said = `${String(count)} ${count === 1 ? noun.replace(/s$/, '') : noun}`
    return more ? `${said}, more to load` : said
}

/** Whether every row this listing holds has been read. */
export function exhausted<T>(state: Paged<T>): boolean {
    return state.read && state.next === null
}
