import { beforeEach, describe, expect, test, vi } from 'vitest'

import {
    filterActions,
    forgetActions,
    paletteActions,
    registerActions,
    shelve,
    type PaletteAction,
} from '@/lib/palette'

function action(id: string, title: string, group = 'Go to', keywords: string[] = []): PaletteAction {
    return { id, title, group, keywords, run: () => undefined }
}

const ROWS = [
    action('go:/pipelines', 'Pipelines'),
    action('go:/runs', 'Runs'),
    action('go:/triggers', 'Triggers', 'Go to', ['cron', 'interval']),
    action('view:rail', 'Collapse the navigation', 'View', ['sidebar']),
    action('session:out', 'Sign out', 'Session', ['logout']),
]

beforeEach(() => {
    forgetActions()
})

describe('registration', () => {
    test('offers what a screen registered, and takes it away again when the screen unmounts', () => {
        const stop = registerActions([action('runs:cancel', 'Cancel this run')])
        expect(paletteActions.get().map((row) => row.id)).toContain('runs:cancel')
        stop()
        expect(paletteActions.get()).toHaveLength(0)
    })

    test('re-registering an id replaces the row rather than duplicating it', () => {
        registerActions([action('runs:cancel', 'Cancel this run')])
        registerActions([action('runs:cancel', 'Cancel this run')])
        expect(paletteActions.get()).toHaveLength(1)
    })

    test('one screen unregistering leaves another screen rows alone', () => {
        const stopShell = registerActions([action('go:/runs', 'Runs')])
        registerActions([action('runs:cancel', 'Cancel this run')])
        stopShell()
        expect(paletteActions.get().map((row) => row.id)).toEqual(['runs:cancel'])
    })

    test('publishes to a watcher, so a screen registering repaints the palette', () => {
        const seen = vi.fn()
        const unwatch = paletteActions.subscribe(seen)
        registerActions([action('runs:cancel', 'Cancel this run')])
        unwatch()
        expect(seen).toHaveBeenCalledOnce()
    })
})

describe('filtering', () => {
    test('an empty query is not a filter: it answers everything, in registration order', () => {
        expect(filterActions(ROWS, '  ')).toHaveLength(ROWS.length)
        expect(filterActions(ROWS, '')[0].id).toBe('go:/pipelines')
    })

    test('finds a row by a word in its title, whatever the case', () => {
        expect(filterActions(ROWS, 'RUNS').map((row) => row.id)).toEqual(['go:/runs'])
    })

    test('finds a row by a keyword nothing renders', () => {
        expect(filterActions(ROWS, 'cron').map((row) => row.id)).toEqual(['go:/triggers'])
    })

    test('every term has to match, so typing more words narrows rather than widens', () => {
        expect(filterActions(ROWS, 'sign out')).toHaveLength(1)
        expect(filterActions(ROWS, 'sign pipelines')).toHaveLength(0)
    })

    test('a title that starts with the query sorts above one that merely contains it', () => {
        const rows = [action('a', 'Cancel this run'), action('b', 'Runs')]
        expect(filterActions(rows, 'run').map((row) => row.id)).toEqual(['b', 'a'])
    })

    test('a title match sorts above a row matched only by a keyword', () => {
        const rows = [action('a', 'Collapse the navigation', 'View', ['schedules']), action('b', 'Schedules')]
        expect(filterActions(rows, 'schedules').map((row) => row.id)).toEqual(['b', 'a'])
    })

    test('a row can also be found by the group it is shelved under', () => {
        expect(filterActions(ROWS, 'session').map((row) => row.id)).toEqual(['session:out'])
    })
})

/** A row the screen in front of somebody registered, which is what leads the shelves. */
function screenRow(id: string, group: string): PaletteAction {
    return { id, title: id, group, screen: true, run: () => undefined }
}

describe('how the rows are shelved', () => {
    test("the screen's own shelf leads, wherever its rows were registered", () => {
        const shelves = shelve([
            action('go:runs', 'Runs', 'Go to'),
            action('view:rail', 'Fold the rail', 'View'),
            screenRow('run:cancel', 'Run — ffff0123'),
        ])
        expect(shelves.map((shelf) => shelf.label)).toEqual(['Run — ffff0123', 'Go to', 'View'])
    })

    test('a shelf keeps the place its first row gave it, once the screen has had its turn', () => {
        const shelves = shelve([
            action('view:rail', 'Fold the rail', 'View'),
            action('go:runs', 'Runs', 'Go to'),
        ])
        expect(shelves.map((shelf) => shelf.label)).toEqual(['View', 'Go to'])
    })

    test('rows keep the order the filter put them in', () => {
        const shelves = shelve([action('a', 'A'), action('b', 'B'), action('c', 'C')])
        expect(shelves[0].rows.map((row) => row.id)).toEqual(['a', 'b', 'c'])
    })

    test("one row claiming the screen makes the shelf the screen's", () => {
        const shelves = shelve([
            action('go:runs', 'Runs', 'Go to'),
            action('list:reload', 'Read it again', 'This listing'),
            screenRow('list:apply', 'This listing'),
        ])
        expect(shelves[0].label).toBe('This listing')
        expect(shelves[0].rows).toHaveLength(2)
    })

    test('shelves nothing when there is nothing to shelve', () => {
        expect(shelve([])).toEqual([])
    })

    test('a shelf whose heading names what it is scoped to is still one shelf', () => {
        const shelves = shelve([
            screenRow('run:cancel', 'Run — ffff0123'),
            screenRow('run:again', 'Run — ffff0123'),
        ])
        expect(shelves).toHaveLength(1)
        expect(shelves[0].rows).toHaveLength(2)
    })
})
