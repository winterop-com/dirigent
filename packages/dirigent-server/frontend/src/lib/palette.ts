/**
 * Everything the command palette can do, as data.
 *
 * A REGISTRY RATHER THAN A FUNCTION OF THE WHOLE APP. The shell registers the entries that are
 * always there -- every page, the appearance rows, sign out -- and a screen registers what only
 * it can do while it is mounted, and takes those rows away again when it unmounts. So the
 * palette on the runs page offers what the runs page offers, and nothing has to hold a list of
 * every screen's actions in one place.
 *
 * The rows are handed to sokkel-ui's palette as its groups, which matches them by every word typed:
 * the failures worth catching here are a page missing from the list, a row whose words are not
 * handed over, and a screen whose rows outlive it.
 *
 * EVERY CHORD THIS APP BINDS IS A LETTER. `lib/shortcuts` says why, and offers each of them as
 * a row here as well, because a shortcut nobody has been told about is a shortcut nobody has.
 */

import type { LucideIcon } from 'lucide-react'
import type { PaletteGroup } from '@winterop-com/sokkel-ui/CommandPalette'

import { NEUTRAL_GLYPH } from '@/lib/glyphs'
import { LABELS } from '@/lib/labels'
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
export const GO_GROUP = LABELS.palette.shelf.go
export const ADMIN_GROUP = LABELS.palette.shelf.admin
export const VIEW_GROUP = LABELS.palette.shelf.view
/** What the screen in front of somebody can do, which only that screen registers. */
export const RUN_GROUP = LABELS.palette.shelf.run
/** What a listing screen offers over its own rows: a filter, a refresh, the verb it owns. */
export const LIST_GROUP = LABELS.palette.shelf.list
/** What the front door offers over the instance it is describing, which is not a listing. */
export const DASHBOARD_GROUP = LABELS.palette.shelf.dashboard
export const APPEARANCE_GROUP = LABELS.palette.shelf.appearance
export const SESSION_GROUP = LABELS.palette.shelf.session

/** Registered rows, oldest registration first. */
const registered = createStore<readonly PaletteAction[]>([])

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

/**
 * The rows as shelves, the screen's own first.
 *
 * THE SCREEN'S SHELF LEADS. Somebody who opened the palette while reading a run wants
 * something to do with that run far more often than they want the fifth navigation row, and a
 * list is read from the top. Within that rule nothing is re-ordered: each shelf keeps the
 * position its first row gave it, and the rows keep the order they were registered in.
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

/**
 * The shelves as the palette's groups. A row is its mark and its title: what it says about itself
 * is a word it is found by and is never drawn, and a row with no mark wears the neutral glyph.
 */
export function paletteGroups(actions: readonly PaletteAction[]): PaletteGroup[] {
    return shelve(actions).map((shelf) => ({
        title: shelf.label,
        commands: shelf.rows.map((row) => ({
            id: row.id,
            label: row.title,
            icon: row.icon ?? NEUTRAL_GLYPH,
            keywords: [...(row.keywords ?? []), ...(row.hint === undefined ? [] : [row.hint])],
            onSelect: row.run,
        })),
    }))
}
