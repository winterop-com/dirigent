import { beforeEach, describe, expect, test, vi } from 'vitest'

import {
    forgetActions,
    paletteActions,
    paletteGroups,
    registerActions,
    shelve,
    type PaletteAction,
} from '@/lib/palette'

function action(id: string, title: string, group = 'Go to', keywords: string[] = []): PaletteAction {
    return { id, title, group, keywords, run: () => undefined }
}

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

    test('rows keep the order they were registered in', () => {
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

describe('the groups handed to the palette', () => {
    test('are the shelves, the screen first, each row its title', () => {
        const groups = paletteGroups([
            action('go:runs', 'Runs', 'Go to'),
            screenRow('run:cancel', 'Run — ffff0123'),
        ])
        expect(groups.map((group) => group.title)).toEqual(['Run — ffff0123', 'Go to'])
        expect(groups[1].commands.map((command) => command.label)).toEqual(['Runs'])
    })

    test('find a row by its hint and its keywords without drawing either', () => {
        const row = { ...action('go:/triggers', 'Triggers', 'Go to', ['cron']), hint: 'when pipelines start' }
        const [command] = paletteGroups([row])[0].commands
        expect(command.keywords).toEqual(['cron', 'when pipelines start'])
        expect(command.hint).toBeUndefined()
    })

    test('give a row with no mark the neutral glyph rather than a gap', () => {
        expect(paletteGroups([action('a', 'A')])[0].commands[0].icon).toBeDefined()
    })
})
