import { describe, expect, test } from 'vitest'

import { groupBlocks } from '@winterop-com/sokkel-ui-graph/blocks'

import { pickerBlocks, pickerGroups, stepKeyFor } from '@/lib/add-step'
import type { BlockEntry } from '@/lib/blocks'
import { LABELS } from '@/lib/labels'

/** A catalog entry with only the members this module reads, which are five of them. */
function block(id: string, kind: BlockEntry['kind'], summary: string, group?: string): BlockEntry {
    return {
        id,
        kind,
        summary,
        group: group ?? id.split('.')[0] ?? id,
        plugin: 'builtin',
        idempotent: true,
        local_execution: false,
        unsafe: false,
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

describe('pickerGroups', () => {
    test('every group the catalog declares, in name order, a group of one still a group', () => {
        expect(pickerGroups(DECLARED).map((group) => group.id)).toEqual([
            'execute',
            'http',
            'transform',
            'webhook',
        ])
    })
})

/** What a search in the picker lists, by block id, in the order it lists them. */
function found(blocks: readonly BlockEntry[], query: string): string[] {
    return groupBlocks(pickerBlocks(blocks), pickerGroups(blocks), query).flatMap((entry) =>
        entry.blocks.map((one) => one.kind),
    )
}

describe('pickerBlocks', () => {
    test('a block is offered under the group it declares, not the half of its id', () => {
        const offered = pickerBlocks(DECLARED)
        expect(offered.find((one) => one.kind === 'map.jq')?.group).toBe('transform')
        expect(offered.find((one) => one.kind === 'docker.run')?.group).toBe('execute')
    })

    test('only a sensor wears a badge', () => {
        const offered = pickerBlocks(DECLARED)
        expect(offered.find((one) => one.kind === 'http.ready')?.badge).toEqual({
            label: 'sensor',
            title: LABELS.editor.canvas.sensor_title,
        })
        expect(offered.filter((one) => one.badge !== undefined)).toHaveLength(1)
    })

    test('a search narrows by id and summary alike', () => {
        expect(found(CATALOG, 'worker')).toEqual(['shell.run'])
        expect(found(CATALOG, 'jq')).toEqual(['transform.jq'])
    })

    test('the word sensor finds every sensor, in the singular and the plural', () => {
        expect(found(CATALOG, 'sensor')).toEqual(['file.wait', 'http.poll'])
        expect(found(CATALOG, 'sensors')).toEqual(['file.wait', 'http.poll'])
    })

    test('the word operator finds every operator, and no sensor', () => {
        expect(found(CATALOG, 'operator')).toEqual(['http.request', 'shell.run', 'transform.jq'])
    })

    test('every term must match, so a second word narrows', () => {
        expect(found(CATALOG, 'http sensor')).toEqual(['http.poll'])
        expect(found(CATALOG, 'http nothing')).toEqual([])
    })

    test('the case somebody typed in is not the case the catalog is written in', () => {
        expect(found(CATALOG, 'JQ')).toEqual(['transform.jq'])
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
