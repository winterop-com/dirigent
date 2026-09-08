/**
 * Everything the command palette can do, as data.
 *
 * A REGISTRY RATHER THAN A FUNCTION OF THE WHOLE APP. The shell registers the entries that are
 * always there -- every page, the appearance rows, sign out -- and a screen registers what only
 * it can do while it is mounted, and takes those rows away again when it unmounts. So the
 * palette on the runs page offers what the runs page offers, and nothing has to hold a list of
 * every screen's actions in one place.
 *
 * THE FILTER IS A PURE FUNCTION over the registered rows, which is what makes the whole action
 * surface testable in plain Node: the failures worth catching are a page missing from the list,
 * a row that cannot be found by a word in its own title, and a screen whose rows outlive it.
 *
 * EVERY CHORD THIS APP BINDS IS A LETTER. `lib/shortcuts` says why, and offers each of them as
 * a row here as well, because a shortcut nobody has been told about is a shortcut nobody has.
 */

import type { LucideIcon } from 'lucide-react'

import { createStore } from '@/lib/store'

/** One thing the palette offers. */
export interface PaletteAction {
    /** Stable across rebuilds of the list, so the renderer can key on it and a test can name it. */
    id: string
    /** What the row is called. The first thing the filter matches on. */
    title: string
    /** The heading the row is shelved under. Rows keep the order they were registered in. */
    group: string
    /** Extra words the filter matches on and nothing renders. */
    keywords?: string[]
    /** More words the search matches -- what the thing is in other vocabularies. Never drawn. */
    hint?: string
    /** The mark in the row's tile. A row without one gets the neutral glyph, never a gap. */
    icon?: LucideIcon
    /**
     * Whether this row belongs to the screen in front of somebody rather than to the app.
     *
     * A screen's own shelf is laid out first, because somebody who opened the palette while
     * looking at a run is far more likely to want something to do with that run than to want
     * the fifth navigation row. The shelf's heading is free to name what it is scoped to.
     */
    screen?: boolean
    /** What choosing the row does. Runs after the palette closes. */
    run: () => void
}

/** One shelf of the palette: its heading, whether it is the screen's, and its rows. */
export interface PaletteShelf {
    label: string
    screen: boolean
    rows: PaletteAction[]
}

/** The shelves, in the order the palette lays them out. */
export const GO_GROUP = 'Go to'
export const ADMIN_GROUP = 'Admin'
export const VIEW_GROUP = 'View'
/** What the screen in front of somebody can do, which only that screen registers. */
export const RUN_GROUP = 'Run'
/** What a listing screen offers over its own rows: a filter, a refresh, the verb it owns. */
export const LIST_GROUP = 'This listing'
/** What the front door offers over the instance it is describing, which is not a listing. */
export const DASHBOARD_GROUP = 'This screen'
export const APPEARANCE_GROUP = 'Appearance'
export const SESSION_GROUP = 'Session'

/** Registered rows, oldest registration first. */
const registered = createStore<readonly PaletteAction[]>([])

/** Whether the palette is on screen. The shortcut and the rail's button both write it. */
export const paletteOpen = createStore(false)

/** The rows currently on offer. */
export const paletteActions = registered

/**
 * Offer these rows until the returned function is called.
 *
 * A screen calls this from an effect and returns the result, so a row cannot outlive the
 * screen that could carry it out. Re-registering the same id replaces the row rather than
 * duplicating it, which is what makes a re-render with new closures safe.
 */
export function registerActions(actions: readonly PaletteAction[]): () => void {
    const ids = new Set(actions.map((action) => action.id))
    registered.update((current) => [...current.filter((action) => !ids.has(action.id)), ...actions])
    return () => {
        registered.update((current) => current.filter((action) => !ids.has(action.id)))
    }
}

/** Forget every registered row. Tests, and nothing else, call this. */
export function forgetActions(): void {
    registered.set([])
}

/** Every word a row can be found by, lowercased. */
function haystack(action: PaletteAction): string {
    return [action.title, action.group, action.hint ?? '', ...(action.keywords ?? [])].join(' ').toLowerCase()
}

/**
 * The rows one query names, best first.
 *
 * EVERY TERM HAS TO MATCH, so typing more words narrows rather than widens -- `run sched`
 * finds the schedules page and not every row with the word "run" in it. A row whose title
 * starts with the query sorts above one that merely contains it, and above one matched only by
 * a keyword, so the obvious answer to a short query is the first row rather than the fourth.
 *
 * An empty query is not a filter: it answers everything, in registration order, which is what
 * a palette opened with no intention should show.
 */
export function filterActions(actions: readonly PaletteAction[], query: string): PaletteAction[] {
    const trimmed = query.trim().toLowerCase()
    if (trimmed === '') return [...actions]
    const terms = trimmed.split(/\s+/)
    const matched = actions.filter((action) => {
        const words = haystack(action)
        return terms.every((term) => words.includes(term))
    })
    return matched
        .map((action, index) => ({ action, index, rank: rankOf(action, trimmed) }))
        .toSorted((left, right) => left.rank - right.rank || left.index - right.index)
        .map((scored) => scored.action)
}

/**
 * The filtered rows as shelves, the screen's own first.
 *
 * THE SCREEN'S SHELF LEADS. Somebody who opened the palette while reading a run wants
 * something to do with that run far more often than they want the fifth navigation row, and a
 * list is read from the top. Within that rule nothing is re-ordered: each shelf keeps the
 * position its first row gave it, and the rows keep the order the filter put them in.
 *
 * A shelf is the screen's when its rows say so, not because of what it is called -- the
 * heading is free to carry the thing it is scoped to, such as the run being read.
 */
export function shelve(actions: readonly PaletteAction[]): PaletteShelf[] {
    const shelves = new Map<string, PaletteShelf>()
    for (const action of actions) {
        const shelf = shelves.get(action.group)
        if (shelf === undefined) {
            shelves.set(action.group, { label: action.group, screen: action.screen === true, rows: [action] })
        } else {
            shelf.rows.push(action)
            // One row claiming the screen makes the shelf the screen's: a screen registers its
            // own group, and a shelf half of which is the screen's is a shelf that is.
            if (action.screen === true) shelf.screen = true
        }
    }
    const found = [...shelves.values()]
    return [...found.filter((shelf) => shelf.screen), ...found.filter((shelf) => !shelf.screen)]
}

/** Where a row sorts for one query: title prefix, then title, then anything else. */
function rankOf(action: PaletteAction, query: string): number {
    const title = action.title.toLowerCase()
    if (title.startsWith(query)) return 0
    if (title.includes(query)) return 1
    return 2
}
