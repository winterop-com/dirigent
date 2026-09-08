import { describe, expect, test } from 'vitest'

import { blockShelves, crumbOf, searchBlocks, stepKeyFor } from '@/lib/add-step'
import type { BlockEntry } from '@/lib/blocks'

/** A catalog entry with only the members this module reads, which are five of them. */
function block(id: string, kind: BlockEntry['kind'], summary: string, group?: string): BlockEntry {
    return {
        id,
        kind,
        summary,
        group: group ?? (id.split('.')[0] ?? id),
        plugin: 'builtin',
        idempotent: true,
        local_execution: false,
        default_poll_seconds: null,
        default_deadline_seconds: null,
        config_schema: {},
        output_schema: {},
    }
}

/** A catalog of blocks that declare the group their id already reads as. */
const CATALOG: BlockEntry[] = [
    block('transform.jq', 'operator', 'Run a jq program over the input.'),
    block('shell.run', 'operator', 'Run a command on the worker.'),
    block('file.wait', 'sensor', 'Wait for a path to appear.'),
    block('http.request', 'operator', 'Send one request.'),
    block('http.poll', 'sensor', 'Poll a URL until it answers.'),
]

/** A catalog whose groups are not the halves of its ids: two verbs on one shelf, two ids on another. */
const DECLARED: BlockEntry[] = [
    block('transform.jq', 'operator', 'Reshape a value.', 'transform'),
    block('map.jq', 'operator', 'Replace every element of a list.', 'transform'),
    block('shell.run', 'operator', 'Run a command on the worker.', 'execute'),
    block('docker.run', 'operator', 'Run a container on the worker.', 'execute'),
    block('webhook.post', 'operator', 'POST a JSON body.', 'webhook'),
    block('http.ready', 'sensor', 'Wait for an endpoint to report ready.', 'http'),
]

describe('blockShelves', () => {
    test('shelves every group in name order, blocks in id order within one', () => {
        const shelves = blockShelves(DECLARED)

        expect(shelves.map((shelf) => shelf.shelf)).toEqual(['execute', 'http', 'transform', 'webhook'])
        expect(shelves[0]?.blocks.map((entry) => entry.id)).toEqual(['docker.run', 'shell.run'])
    })

    test('a block shelves where it says it belongs, not where the half of its id reads', () => {
        const shelves = blockShelves(DECLARED)

        expect(shelves.find((shelf) => shelf.shelf === 'transform')?.blocks.map((entry) => entry.id)).toEqual([
            'map.jq',
            'transform.jq',
        ])
        expect(shelves.map((shelf) => shelf.shelf)).not.toContain('map')
    })

    test('a group of one is a shelf of one, which the menu draws as a row rather than a submenu', () => {
        expect(blockShelves(DECLARED).find((shelf) => shelf.shelf === 'webhook')?.blocks).toHaveLength(1)
    })

    test('a sensor keeps its place in its own group as well', () => {
        const shelves = blockShelves(CATALOG)

        expect(shelves.find((shelf) => shelf.shelf === 'file')?.blocks.map((entry) => entry.id)).toEqual([
            'file.wait',
        ])
    })
})

describe('crumbOf', () => {
    test('splits an id at its first dot', () => {
        expect(crumbOf(block('transform.jq', 'operator', ''))).toMatchObject({ family: 'transform', rest: 'jq' })
    })

    test('an id with no dot is its own family and its own remainder', () => {
        expect(crumbOf(block('noop', 'operator', ''))).toMatchObject({ family: 'noop', rest: 'noop' })
    })

    test('only the first dot splits, so the rest keeps its own', () => {
        expect(crumbOf(block('std.convert.csv', 'operator', ''))).toMatchObject({
            family: 'std',
            rest: 'convert.csv',
        })
    })
})

describe('searchBlocks', () => {
    test('an empty needle finds nothing, because the shelves are what an empty box shows', () => {
        expect(searchBlocks(CATALOG, '')).toEqual([])
        expect(searchBlocks(CATALOG, '   ')).toEqual([])
    })

    test('narrows by id and summary alike, in id order, breadcrumbed', () => {
        // `run` is in one id and in another's summary, and both are what somebody typing it means.
        expect(searchBlocks(CATALOG, 'ru')).toMatchObject([
            { family: 'shell', rest: 'run' },
            { family: 'transform', rest: 'jq' },
        ])
    })

    test('narrows by summary as well as by id', () => {
        expect(searchBlocks(CATALOG, 'worker').map((crumb) => crumb.entry.id)).toEqual(['shell.run'])
    })

    test('the word sensor matches by kind, in the singular and the plural', () => {
        expect(searchBlocks(CATALOG, 'sensor').map((crumb) => crumb.entry.id)).toEqual(['file.wait', 'http.poll'])
        expect(searchBlocks(CATALOG, 'sensors').map((crumb) => crumb.entry.id)).toEqual(['file.wait', 'http.poll'])
    })

    test('the word operator matches by kind, and no sensor with it', () => {
        expect(searchBlocks(CATALOG, 'operator').map((crumb) => crumb.entry.id)).toEqual([
            'http.request',
            'shell.run',
            'transform.jq',
        ])
    })

    test('every term must match, so a second word narrows', () => {
        expect(searchBlocks(CATALOG, 'http sensor').map((crumb) => crumb.entry.id)).toEqual(['http.poll'])
        expect(searchBlocks(CATALOG, 'http nothing')).toEqual([])
    })

    test('the case somebody typed in is not the case the catalog is written in', () => {
        expect(searchBlocks(CATALOG, 'JQ').map((crumb) => crumb.entry.id)).toEqual(['transform.jq'])
    })
})

describe('stepKeyFor', () => {
    test('a step is keyed by the block it runs, without its family', () => {
        expect(stepKeyFor('transform.jq', [])).toBe('jq')
    })

    test('a key the document already has is numbered from two', () => {
        expect(stepKeyFor('transform.jq', ['jq'])).toBe('jq_2')
        expect(stepKeyFor('transform.jq', ['jq', 'jq_2'])).toBe('jq_3')
    })

    test('two families offering the same name still key apart', () => {
        expect(stepKeyFor('docker.run', [stepKeyFor('shell.run', [])])).toBe('run_2')
    })

    test('what the key pattern refuses is written as an underscore', () => {
        expect(stepKeyFor('std.convert.csv', [])).toBe('convert_csv')
        expect(stepKeyFor('http.get-once', [])).toBe('get_once')
    })

    test('a name that could not start a key is prefixed rather than refused', () => {
        expect(stepKeyFor('odd.9lives', [])).toBe('step_9lives')
    })

    test('a block with no dot is keyed by the whole of its id', () => {
        expect(stepKeyFor('noop', [])).toBe('noop')
    })
})
