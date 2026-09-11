import { describe, expect, test } from 'vitest'

import {
    byGroup,
    configSummary,
    defaultLabel,
    factsOf,
    groupOf,
    narrowBlocks,
    typeLabel,
    type BlockEntry,
} from '@/lib/blocks'
import { fieldsOf, type FieldDescriptor } from '@/lib/schema-form'

/**
 * Three of the keys the shipped catalog answers with for the one block that executes code.
 *
 * The schema is the shape `pydantic` publishes in serialization mode: attribute docstrings as
 * `description`, a nullable union written as `anyOf`, and a bounded number. A field built from
 * a `default_factory` -- `argv` is one -- carries no `default` at all, which is why the
 * fallback tests below build their own descriptors rather than leaning on this.
 */
const SHELL: BlockEntry = {
    id: 'shell.run',
    kind: 'operator',
    summary: 'Run a command on the worker.',
    group: 'execute',
    plugin: 'builtin',
    idempotent: false,
    local_execution: true,
    default_poll_seconds: null,
    default_deadline_seconds: null,
    config_schema: {
        description: 'What to run, where, with what environment, and for how long.',
        additionalProperties: false,
        properties: {
            argv: {
                type: 'array',
                items: { type: 'string' },
                description: 'The command as an argument vector, which does not involve a shell.',
            },
            command: {
                anyOf: [{ type: 'string' }, { type: 'null' }],
                contentMediaType: 'text/x-shellscript',
                default: null,
                description: 'The command as a shell string, for when a pipe or a redirect is the point.',
            },
            timeout_seconds: {
                type: 'number',
                exclusiveMinimum: 0,
                default: 300,
                description: 'How long the process may run before it is killed as a transient failure.',
            },
        },
        required: [],
        type: 'object',
    },
    output_schema: {},
}

/** A sensor, which is the entry that carries both of the timing defaults. */
const SLEEP: BlockEntry = {
    id: 'time.sleep',
    kind: 'sensor',
    summary: 'Wait a fixed duration.',
    group: 'time',
    plugin: 'builtin',
    idempotent: false,
    local_execution: false,
    default_poll_seconds: 60,
    default_deadline_seconds: 86400,
    config_schema: {},
    output_schema: {},
}

/** One field descriptor, for the labels that read one rather than a whole schema. */
function field(over: Partial<FieldDescriptor> = {}): FieldDescriptor {
    return {
        name: 'argv',
        kind: 'json',
        placeholder: '',
        help: null,
        required: false,
        nullable: false,
        fallback: undefined,
        options: [],
        mediaType: null,
        hint: null,
        bounds: {},
        accepts: [],
        ...over,
    }
}

describe('the shelf a block belongs on', () => {
    /** The same id twice under one declared group, which no id-derived shelving would give. */
    const JQ: BlockEntry = { ...SHELL, id: 'map.jq', summary: 'Map a list.', group: 'transform' }
    const TRANSFORM: BlockEntry = { ...SHELL, id: 'transform.jq', summary: 'Reshape.', group: 'transform' }

    test('is the group the catalog answered with, never the half of the id', () => {
        expect(groupOf(SHELL)).toBe('execute')
        expect(groupOf(JQ)).toBe('transform')
    })

    test('shelves by group, groups in name order and blocks in id order within one', () => {
        expect(byGroup([TRANSFORM, SHELL, JQ, SLEEP])).toEqual([
            ['execute', [SHELL]],
            ['time', [SLEEP]],
            ['transform', [JQ, TRANSFORM]],
        ])
    })

    test('leaves a group of one as a shelf of one, which is what the menu draws as a row', () => {
        expect(byGroup([SHELL, SLEEP]).map(([group, members]) => [group, members.length])).toEqual([
            ['execute', 1],
            ['time', 1],
        ])
    })

    test('shelves nothing when the catalog is empty rather than inventing a heading', () => {
        expect(byGroup([])).toEqual([])
    })
})

describe('narrowing the catalog', () => {
    test('finds a block by its id, which is the only thing it is addressed by', () => {
        expect(narrowBlocks([SHELL, SLEEP], 'shell').map((entry) => entry.id)).toEqual(['shell.run'])
    })

    test('finds a block by what it says it does, so a search reads as a search', () => {
        expect(narrowBlocks([SHELL, SLEEP], 'duration').map((entry) => entry.id)).toEqual(['time.sleep'])
    })

    test('ignores case and surrounding space, because a box is typed into by a person', () => {
        expect(narrowBlocks([SHELL, SLEEP], '  SHELL.RUN ').map((entry) => entry.id)).toEqual(['shell.run'])
    })

    test('an empty box is every block rather than none', () => {
        expect(narrowBlocks([SHELL, SLEEP], '   ')).toHaveLength(2)
    })

    test('answers a copy, so a screen holding the result cannot reorder the catalog', () => {
        const catalog = [SHELL, SLEEP]
        expect(narrowBlocks(catalog, '')).not.toBe(catalog)
    })

    test('says nothing matches rather than falling back to everything', () => {
        expect(narrowBlocks([SHELL, SLEEP], 'kubernetes')).toEqual([])
    })
})

describe('how much config a block takes', () => {
    test('counts the keys the schema publishes', () => {
        expect(configSummary(fieldsOf(SHELL.config_schema))).toBe('3 fields')
    })

    test('never says one fields', () => {
        expect(configSummary([field()])).toBe('1 field')
    })

    test('a block taking no config says none rather than nothing at all', () => {
        expect(configSummary(fieldsOf(SLEEP.config_schema))).toBe('none')
    })
})

describe('the type a field takes', () => {
    /**
     * A REFERENCE STATES A SHAPE, NOT A CONTROL. `FieldDescriptor.kind` is what the step form
     * picks a widget with, and `switch` is a widget rather than a type -- a reader looking up
     * what a document may carry is owed the word the schema is written in.
     */
    test('reads as the schema word rather than the control the step form would draw', () => {
        expect(typeLabel(field({ kind: 'switch' }))).toBe('boolean')
        expect(typeLabel(field({ kind: 'text' }))).toBe('string')
        expect(typeLabel(field({ kind: 'select' }))).toBe('enum')
        expect(typeLabel(field({ kind: 'integer' }))).toBe('integer')
        expect(typeLabel(field({ kind: 'json' }))).toBe('json')
    })

    test('says so when the schema also allowed null', () => {
        expect(typeLabel(field({ kind: 'text', nullable: true }))).toBe('string or null')
    })

    test('names the language of a field the schema published as a program', () => {
        expect(typeLabel(field({ kind: 'code', mediaType: 'application/jq' }))).toBe(
            'string (application/jq)',
        )
    })

    test('reads shell.run the way its schema is written', () => {
        const fields = fieldsOf(SHELL.config_schema)
        const by = (name: string) => fields.find((one) => one.name === name)
        expect(typeLabel(by('argv') as FieldDescriptor)).toBe('json')
        expect(typeLabel(by('command') as FieldDescriptor)).toBe('string (text/x-shellscript) or null')
        expect(typeLabel(by('timeout_seconds') as FieldDescriptor)).toBe('number')
    })
})

describe('what a field falls back to', () => {
    /**
     * THE REVERT-PROOF ONE. `String([])` is the empty string and `String({})` is
     * `[object Object]` -- so a schema whose default is a list would read on screen as a field
     * with no default at all, beside one that genuinely has none. A structure is written as
     * the JSON it is.
     */
    test('writes a list or a map as JSON rather than as the empty string', () => {
        expect(defaultLabel(field({ fallback: [] }))).toBe('[]')
        expect(defaultLabel(field({ fallback: { a: 1 } }))).toBe('{"a":1}')
    })

    test('a schema with no default has none to state', () => {
        expect(defaultLabel(field())).toBeNull()
    })

    test('a default of null is a default, and is not the same as having none', () => {
        expect(defaultLabel(field({ fallback: null }))).toBe('null')
    })

    test('writes a number and a boolean as themselves', () => {
        expect(defaultLabel(field({ fallback: 300 }))).toBe('300')
        expect(defaultLabel(field({ fallback: false }))).toBe('false')
    })
})

describe('the facts a block carries besides its schemas', () => {
    test('names each fact with the word the catalog answers with', () => {
        expect(factsOf(SHELL).map((fact) => fact.term)).toEqual(['plugin', 'idempotent', 'local_execution'])
    })

    /**
     * THE ONE THAT DECIDES WHETHER A PIPELINE RUNS. `local_execution` is the allowlist gate, so
     * it is stated in both directions: a row that appeared only when the answer was yes would
     * leave its absence meaning either no or not-read.
     */
    test('says a block that executes code needs allowlisting', () => {
        const fact = factsOf(SHELL).find((one) => one.term === 'local_execution')
        expect(fact?.detail).toBe('requires allowlisting')
    })

    test('says as much about a block that does not', () => {
        const fact = factsOf(SLEEP).find((one) => one.term === 'local_execution')
        expect(fact?.detail).toBe('no allowlist entry')
    })

    test('states the timing defaults a sensor carries, in the seconds the wire counts', () => {
        expect(factsOf(SLEEP)).toContainEqual({ term: 'default_poll_seconds', detail: '60s' })
        expect(factsOf(SLEEP)).toContainEqual({ term: 'default_deadline_seconds', detail: '86400s' })
    })

    test('leaves out a timing an operator does not carry rather than drawing an empty row', () => {
        const terms = factsOf(SHELL).map((fact) => fact.term)
        expect(terms).not.toContain('default_poll_seconds')
        expect(terms).not.toContain('default_deadline_seconds')
    })
})
