import { describe, expect, test } from 'vitest'

import type { JsonMap } from '@/lib/api'
import {
    fieldsOf,
    optionLabel,
    validateField,
    sameJson,
    validateFields,
    type FieldDescriptor,
} from '@/lib/schema-form'

/**
 * Every shape in this file is transcribed from a schema the shipped catalog actually publishes.
 *
 * The catalog was surveyed for the distinct property shapes across all fourteen blocks, and
 * each one has a case here: a plain scalar, a bounded number, an enum reached through `$ref`,
 * pydantic's two spellings of optional, a union of two scalars, a list, a map of scalars, a map
 * of any JSON value, and a member with no type at all. A block whose config takes a shape none
 * of these cover is a block whose form silently renders the wrong control, so the fallback has a
 * test of its own.
 *
 * TWO MAPS HERE ARE NOT IN THE CATALOG: a map of integers and a map of booleans. What is under
 * test is the `pairs` kind's own rule -- a cell refuses what its type refuses -- and a rule is
 * tested where it is written rather than left for the first pack that publishes such a map.
 */

/** `$defs` as the catalog writes them, shared by the schemas below. */
const DEFS: JsonMap = {
    Size: {
        anyOf: [
            { pattern: '^\\d+(?:\\.\\d+)?(?:[TtGgMmKk]?[Ii]?[Bb])?$', type: 'string' },
            { minimum: 0, type: 'integer' },
        ],
        format: 'size',
    },
    HttpMethod: { enum: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'], type: 'string' },
    DayName: { enum: ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'], type: 'string' },
    EntityName: { maxLength: 63, minLength: 1, pattern: '^[a-z](-?[a-z0-9])*$', type: 'string' },
    JsonValue: {},
    Duration: { type: 'string' },
    SchemaRef: { type: 'string', 'x-dirigent-ref': 'schema' },
    ConnectionRef: { type: 'string', 'x-dirigent-ref': 'connection' },
}

/** The union `http.request.query` allows one value to be, which is every scalar type. */
const SCALARS: JsonMap = {
    anyOf: [{ type: 'string' }, { type: 'integer' }, { type: 'number' }, { type: 'boolean' }],
}

/** One property, wrapped in the closed object schema every block config is. */
function schemaOf(properties: JsonMap, required: string[] = []): JsonMap {
    return {
        $defs: DEFS,
        additionalProperties: false,
        type: 'object',
        title: 'BlockConfig',
        properties,
        ...(required.length > 0 ? { required } : {}),
    }
}

function only(properties: JsonMap, required: string[] = []): FieldDescriptor {
    const fields = fieldsOf(schemaOf(properties, required))
    expect(fields).toHaveLength(1)
    return fields[0]
}

describe('the shapes the shipped catalog publishes', () => {
    test('a plain string is a text field labelled by its key, helped by its description', () => {
        // convert.std.from
        const field = only(
            {
                from: {
                    description: 'The format the input is in.',
                    minLength: 1,
                    title: 'From',
                    type: 'string',
                },
            },
            ['from'],
        )
        expect(field).toMatchObject({ name: 'from', kind: 'text', help: 'The format the input is in.' })
        expect(field.bounds.minLength).toBe(1)
    })

    test('a bounded integer is an integer field carrying both bounds', () => {
        // pipeline.run.max_depth
        const field = only({
            max_depth: { default: 5, maximum: 32, minimum: 1, title: 'Max Depth', type: 'integer' },
        })
        expect(field.kind).toBe('integer')
        expect(field.fallback).toBe(5)
        expect(field.bounds).toMatchObject({ minimum: 1, maximum: 32 })
    })

    test('a number with an exclusive bound keeps it exclusive', () => {
        // docker.run.api_timeout_seconds
        const field = only({ api_timeout_seconds: { default: 60.0, exclusiveMinimum: 0.0, type: 'number' } })
        expect(field.kind).toBe('number')
        expect(field.bounds.exclusiveMinimum).toBe(0)
    })

    test('a boolean is a switch, and its default is what the switch starts at', () => {
        // docker.run.pull
        const field = only({
            pull: { default: false, description: 'Pull the image first.', type: 'boolean' },
        })
        expect(field.kind).toBe('switch')
        expect(field.fallback).toBe(false)
    })

    test('an enum reached through a $ref is a select over the values, in the schema order', () => {
        // http.request.method. Breaking this renders a free-text box for a closed set.
        const field = only({ method: { $ref: '#/$defs/HttpMethod', default: 'GET' } })
        expect(field.kind).toBe('select')
        expect(field.options.map((option) => option.value)).toEqual([
            'GET',
            'POST',
            'PUT',
            'PATCH',
            'DELETE',
            'HEAD',
            'OPTIONS',
        ])
        expect(field.options.map((option) => option.label)).toEqual([
            'GET',
            'POST',
            'PUT',
            'PATCH',
            'DELETE',
            'HEAD',
            'OPTIONS',
        ])
        expect(field.fallback).toBe('GET')
    })

    test('a $ref keeps the outer description and default rather than the definition alone', () => {
        // convert.std.max_input: a union of two scalars, so it is typed and says what it takes.
        const field = only({
            max_input: {
                $ref: '#/$defs/Size',
                default: '32mb',
                description: 'How much is read into memory.',
            },
        })
        expect(field).toMatchObject({ kind: 'text', fallback: '32mb', help: 'How much is read into memory.' })
        expect(field.hint).toBe('bytes, or a size such as 16KB or 2MB')
    })

    test('an optional string is one nullable text field, not a union of two', () => {
        // convert.std.input
        const field = only({
            input: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null, description: 'The text.' },
        })
        expect(field).toMatchObject({ kind: 'text', nullable: true, required: false, fallback: null })
    })

    test('an optional number keeps the bound the non-null branch carried', () => {
        // docker.run.cpus
        const field = only({
            cpus: { anyOf: [{ exclusiveMinimum: 0.0, type: 'number' }, { type: 'null' }], default: null },
        })
        expect(field).toMatchObject({ kind: 'number', nullable: true })
        expect(field.bounds.exclusiveMinimum).toBe(0)
    })

    test('an optional $ref is followed through to the definition it names', () => {
        // docker.run.memory, and time.sleep.for through Duration.
        const field = only({
            memory: { anyOf: [{ $ref: '#/$defs/Size', ge: 6291456 }, { type: 'null' }], default: null },
        })
        expect(field).toMatchObject({ kind: 'text', nullable: true })
    })

    test('a format is said beside the label in the reader words this app has for it', () => {
        // convert.std.save_to
        const field = only({
            save_to: { anyOf: [{ format: 'storage-uri', type: 'string' }, { type: 'null' }], default: null },
        })
        expect(field.hint).toBe('a storage URI such as s3://bucket/key')
    })

    test('a format this app has no words for is shown as the schema spelled it', () => {
        const field = only({ when: { format: 'hostname', type: 'string' } })
        expect(field.hint).toBe('hostname')
    })

    test('a union with no format still says its shapes in reader words', () => {
        const field = only({ pick: { anyOf: [{ type: 'string' }, { type: 'integer' }] } })
        expect(field.hint).toBe('text or a whole number')
    })

    test('a string carrying a media type is a program, edited as one and told which language', () => {
        // transform.jq.program, and map.jq and filter.jq through the same config.
        const field = only(
            {
                program: {
                    contentMediaType: 'application/jq',
                    description: 'The jq program this step runs.',
                    minLength: 1,
                    title: 'Program',
                    type: 'string',
                },
            },
            ['program'],
        )
        expect(field).toMatchObject({ kind: 'code', mediaType: 'application/jq', required: true })
        expect(field.bounds).toMatchObject({ minLength: 1 })
    })

    test('a media type on a nullable string is read through the union pydantic writes it as', () => {
        // shell.run.command, and docker.run.command through the same marker.
        const field = only({
            command: {
                anyOf: [{ type: 'string' }, { type: 'null' }],
                contentMediaType: 'text/x-shellscript',
                default: null,
            },
        })
        expect(field).toMatchObject({ kind: 'code', mediaType: 'text/x-shellscript', nullable: true })
    })

    test('a string with no media type stays one line, whatever else it carries', () => {
        // shell.run.cwd: a path is not a program, and length is not what earns an editor.
        const field = only({ cwd: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null } })
        expect(field).toMatchObject({ kind: 'text', mediaType: null })
    })

    test('a pattern travels to the field so a bad name is refused before the apply is', () => {
        // pipeline.run.pipeline
        const field = only(
            { pipeline: { $ref: '#/$defs/EntityName', description: 'The pipeline to run.' } },
            ['pipeline'],
        )
        expect(field.bounds).toMatchObject({ pattern: '^[a-z](-?[a-z0-9])*$', minLength: 1, maxLength: 63 })
    })
})

describe('the shapes no control fits, which are edited as JSON', () => {
    test('a list of strings', () => {
        // docker.run.argv
        expect(only({ argv: { items: { type: 'string' }, title: 'Argv', type: 'array' } }).kind).toBe('json')
    })

    test('a list of integers', () => {
        // http.ready.expect_status
        expect(only({ expect_status: { items: { type: 'integer' }, type: 'array' } }).kind).toBe('json')
    })

    test('a list of an enum, which is a set rather than a choice', () => {
        // time.window.days
        expect(only({ days: { items: { $ref: '#/$defs/DayName' }, type: 'array' } }).kind).toBe('json')
    })

    test('a member with no type at all, which is any JSON value', () => {
        // webhook.post.body, through JsonValue.
        expect(only({ body: { $ref: '#/$defs/JsonValue', description: 'The payload.' } }).kind).toBe('json')
    })

    test('an optional any-JSON member is nullable JSON', () => {
        // filter.jq.input
        const field = only({
            input: { anyOf: [{ $ref: '#/$defs/JsonValue' }, { type: 'null' }], default: null },
        })
        expect(field).toMatchObject({ kind: 'json', nullable: true })
    })

    test('a shape this bundle was built before falls back to JSON rather than to a wrong box', () => {
        expect(only({ later: { type: 'quaternion', title: 'Later' } }).kind).toBe('json')
    })

    test('a $ref naming a definition that is not there falls back too', () => {
        expect(only({ missing: { $ref: '#/$defs/Nothing' } }).kind).toBe('json')
    })
})

describe('a map of scalars, which is a table of pairs', () => {
    test('a map of strings is a table, and its cells hold text', () => {
        // docker.run.env, http.request.headers, webhook.post.headers, a connection kind's headers.
        const field = only({ env: { additionalProperties: { type: 'string' }, type: 'object' } })
        expect(field.kind).toBe('pairs')
        expect(field.holds).toEqual(['text'])
    })

    test('a map of a union of scalars keeps every shape a cell may hold, in schema order', () => {
        // http.request.query
        const field = only({ query: { additionalProperties: SCALARS, type: 'object' } })
        expect(field.kind).toBe('pairs')
        expect(field.holds).toEqual(['text', 'integer', 'number', 'switch'])
    })

    test('a map of integers is a table whose cells refuse anything else', () => {
        const field = only({ ports: { additionalProperties: { type: 'integer' }, type: 'object' } })
        expect(field.kind).toBe('pairs')
        expect(field.holds).toEqual(['integer'])
    })

    test('a table says what a cell takes when it is anything but text, and stays quiet when it is', () => {
        expect(only({ query: { additionalProperties: SCALARS, type: 'object' } }).hint).toBe(
            'values are text or a number or true or false',
        )
        expect(only({ ports: { additionalProperties: { type: 'integer' }, type: 'object' } }).hint).toBe(
            'values are a whole number',
        )
        expect(only({ env: { additionalProperties: { type: 'string' }, type: 'object' } }).hint).toBeNull()
    })

    test('a nullable map is still a table, and clearing it is a value', () => {
        const field = only({
            env: {
                anyOf: [{ additionalProperties: { type: 'string' }, type: 'object' }, { type: 'null' }],
                default: null,
            },
        })
        expect(field).toMatchObject({ kind: 'pairs', nullable: true })
    })
})

describe('the maps a table cannot draw, which stay JSON', () => {
    test('a map of any JSON value stays JSON, because a cell is not a JSON editor', () => {
        // pipeline.run.params
        expect(
            only({ params: { additionalProperties: { $ref: '#/$defs/JsonValue' }, type: 'object' } }).kind,
        ).toBe('json')
    })

    test('a map of lists stays JSON', () => {
        expect(
            only({
                tags: { additionalProperties: { items: { type: 'string' }, type: 'array' }, type: 'object' },
            }).kind,
        ).toBe('json')
    })

    test('a map of maps stays JSON', () => {
        expect(
            only({
                nested: {
                    additionalProperties: { additionalProperties: { type: 'string' }, type: 'object' },
                    type: 'object',
                },
            }).kind,
        ).toBe('json')
    })

    test('an object with properties of its own is not a map at all', () => {
        expect(
            only({
                window: {
                    type: 'object',
                    properties: { start: { type: 'string' }, end: { type: 'string' } },
                },
            }).kind,
        ).toBe('json')
    })

    test('an object open to anything stays JSON, because it says nothing about its values', () => {
        expect(only({ extra: { additionalProperties: true, type: 'object' } }).kind).toBe('json')
        expect(only({ closed: { additionalProperties: false, type: 'object' } }).kind).toBe('json')
    })

    test('a map whose values may be null stays JSON, because an empty cell is not null', () => {
        expect(
            only({
                env: {
                    additionalProperties: { anyOf: [{ type: 'string' }, { type: 'null' }] },
                    type: 'object',
                },
            }).kind,
        ).toBe('json')
    })

    test('a map of an enum stays JSON, because a cell is not a select', () => {
        expect(
            only({ methods: { additionalProperties: { $ref: '#/$defs/HttpMethod' }, type: 'object' } }).kind,
        ).toBe('json')
    })

    test('a map of programs stays JSON, because a cell is not an editor', () => {
        expect(
            only({
                programs: {
                    additionalProperties: { contentMediaType: 'application/jq', type: 'string' },
                    type: 'object',
                },
            }).kind,
        ).toBe('json')
    })
})

describe('a reference standing for a whole map', () => {
    const TEXT = only({ env: { additionalProperties: { type: 'string' }, type: 'object' } })

    test('a reference is not refused, the way one in a JSON textarea never was', () => {
        expect(validateField(TEXT, '${steps.read.output.env}', true)).toBeNull()
    })

    test('a string that is no reference is not a map either, and says so', () => {
        expect(validateField(TEXT, 'whatever', true)).toBe('env must be a map, or a reference to one')
    })
})

/**
 * The rule the server applies, on the client's side of the same document.
 *
 * `defer_references` replaces every value carrying a live `${...}` with a sentinel that every
 * JSON Schema keyword passes over, so a step's config is checked for its shape and not for what
 * a run has yet to resolve. A form that refused one would be refusing a document that applies.
 */
describe('a value written as a reference', () => {
    // playground.generate.delay, which is what put a red box under a valid document.
    const DELAY = only({
        delay: {
            default: '0s',
            format: 'humane-duration',
            pattern: '^(?:(?:\\d+(?:\\.\\d+)?(?:ms|[wdhms]))+|\\d+(?:\\.\\d+)?)$',
            type: 'string',
        },
    })
    const MIN_SIZE = only({ min_size: { $ref: '#/$defs/Size', default: 0 } })
    const ROWS = only({ rows: { default: 10, maximum: 1000, minimum: 0, type: 'integer' } })
    const LEVEL = only({
        level: { default: 'info', enum: ['debug', 'info', 'warning', 'error'], type: 'string' },
    })
    const WAIT = only({ wait: { default: true, type: 'boolean' } })
    const PIPELINE = only({ pipeline: { $ref: '#/$defs/EntityName' } }, ['pipeline'])
    const PORTS = only({ ports: { additionalProperties: { type: 'integer' }, type: 'object' } })

    test('a humane duration carrying one is not held to its pattern', () => {
        expect(validateField(DELAY, '${params.pace}', true)).toBeNull()
        expect(validateField(DELAY, '10s', true)).toBeNull()
        expect(validateField(DELAY, 'soon', true)).toBe(`delay does not match ${DELAY.bounds.pattern ?? ''}`)
    })

    test('every other constrained kind a document may write one in takes it too', () => {
        // A size, a bounded integer, a choice, a switch and a pattern on a code.
        expect(validateField(MIN_SIZE, '${params.floor}', true)).toBeNull()
        expect(validateField(ROWS, '${params.rows}', true)).toBeNull()
        expect(validateField(LEVEL, '${params.level}', true)).toBeNull()
        expect(validateField(WAIT, '${params.wait}', true)).toBeNull()
        expect(validateField(PIPELINE, '${params.child}', true)).toBeNull()
    })

    test('an interpolated value is deferred whole, the way the server defers it', () => {
        expect(validateField(PIPELINE, '${params.tenant}-nightly', true)).toBeNull()
    })

    test('the escape is a literal, so it is checked like any other text', () => {
        expect(validateField(PIPELINE, '$${params.child}', true)).toBe(
            `pipeline does not match ${PIPELINE.bounds.pattern ?? ''}`,
        )
    })

    test('empty braces name nothing, so they are text and are checked as text', () => {
        expect(validateField(DELAY, '${}', true)).toBe(`delay does not match ${DELAY.bounds.pattern ?? ''}`)
    })

    test('one entry of a map may be a reference while the rest are read', () => {
        expect(validateField(PORTS, { http: '${params.port}', https: 443 }, true)).toBeNull()
        expect(validateField(PORTS, { http: 'eighty' }, true)).toBe('ports.http must be a whole number')
    })

    test('nothing is deferred where the values are not a document', () => {
        // A run's parameters and a connection's config are values, and the server checks those
        // literally, so a form over them refuses a reference before the server has to.
        expect(validateField(DELAY, '${params.pace}')).toBe(
            `delay does not match ${DELAY.bounds.pattern ?? ''}`,
        )
        expect(validateFields([ROWS], { rows: '${params.rows}' })).toEqual({ rows: 'rows must be a number' })
        expect(validateFields([ROWS], { rows: '${params.rows}' }, true)).toEqual({})
    })
})

describe('what is wrong with a map the document already carries', () => {
    const TEXT = only({ env: { additionalProperties: { type: 'string' }, type: 'object' } })
    const WHOLE = only({ ports: { additionalProperties: { type: 'integer' }, type: 'object' } })
    const ANY = only({ query: { additionalProperties: SCALARS, type: 'object' } })

    test('a map of the right shape is fine, and so is an empty one', () => {
        expect(validateField(TEXT, { PATH: '/usr/bin' })).toBeNull()
        expect(validateField(TEXT, {})).toBeNull()
        expect(validateField(ANY, { page: 2, since: '2026-01-01', deep: true, ratio: 1.5 })).toBeNull()
    })

    test('a value of the wrong shape is named by the key that carries it', () => {
        expect(validateField(TEXT, { PATH: 3 })).toBe('env.PATH must be text')
        expect(validateField(WHOLE, { http: 1.5 })).toBe('ports.http must be a whole number')
        expect(validateField(ANY, { page: [] })).toBe('query.page must be text or a number or true or false')
    })

    test('a list where a map goes says it is a map, or a reference to one', () => {
        expect(validateField(TEXT, ['PATH'])).toBe('env must be a map, or a reference to one')
        expect(validateField(TEXT, 3)).toBe('env must be a map, or a reference to one')
    })

    test('a form with a bad map in it may not be sent', () => {
        expect(validateFields([TEXT], { env: { PATH: 3 } })).toEqual({ env: 'env.PATH must be text' })
        expect(validateFields([TEXT], { env: { PATH: '/usr/bin' } })).toEqual({})
    })
})

describe('what the schema says is required', () => {
    test('is marked on exactly the fields it lists, and on no others', () => {
        // Breaking this stops a form saying which fields an apply will refuse it without.
        const fields = fieldsOf(
            schemaOf({ from: { type: 'string' }, to: { type: 'string' }, input: { type: 'string' } }, [
                'from',
                'to',
            ]),
        )
        expect(fields.filter((field) => field.required).map((field) => field.name)).toEqual(['from', 'to'])
    })

    test('is nothing at all when the schema lists none', () => {
        const fields = fieldsOf(schemaOf({ pull: { type: 'boolean' } }))
        expect(fields.every((field) => !field.required)).toBe(true)
    })
})

describe('a schema with no form in it', () => {
    test('a block taking no config has no fields', () => {
        expect(fieldsOf({ type: 'object', properties: {}, additionalProperties: false })).toEqual([])
    })

    test('a schema that is not an object schema has none either', () => {
        expect(fieldsOf({ type: 'string' })).toEqual([])
        expect(fieldsOf(null)).toEqual([])
    })

    test('the fields come back in the order the schema lists them', () => {
        const fields = fieldsOf(
            schemaOf({ from: { type: 'string' }, to: { type: 'string' }, pull: { type: 'boolean' } }),
        )
        expect(fields.map((field) => field.name)).toEqual(['from', 'to', 'pull'])
    })
})

describe('what is wrong with a value', () => {
    const required = only({ from: { minLength: 1, type: 'string' } }, ['from'])
    const method = only({ method: { $ref: '#/$defs/HttpMethod', default: 'GET' } })
    const depth = only({ max_depth: { maximum: 32, minimum: 1, type: 'integer' } })
    const optional = only({ input: { anyOf: [{ type: 'string' }, { type: 'null' }], default: null } })

    test('a required field with nothing in it is named as required', () => {
        expect(validateField(required, undefined)).toBe('from is required')
    })

    test('an optional field with nothing in it is not a problem', () => {
        expect(validateField(optional, undefined)).toBeNull()
    })

    test('null is a value where the schema allowed one, and not where it did not', () => {
        expect(validateField(optional, null)).toBeNull()
        expect(validateField(required, null)).toBe('from may not be null')
    })

    test('a value outside an enum is refused, naming what it may be', () => {
        expect(validateField(method, 'TRACE')).toBe(
            'method must be one of GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS',
        )
        expect(validateField(method, 'POST')).toBeNull()
    })

    test('a number outside its bounds is refused at the bound it broke', () => {
        expect(validateField(depth, 0)).toBe('max_depth must be at least 1')
        expect(validateField(depth, 33)).toBe('max_depth must be at most 32')
        expect(validateField(depth, 5)).toBeNull()
    })

    test('a fraction where the schema says integer is refused', () => {
        expect(validateField(depth, 2.5)).toBe('max_depth must be a whole number')
    })

    test('a value below an exclusive bound is refused at zero, which a minimum would allow', () => {
        const cpus = only({ cpus: { exclusiveMinimum: 0, type: 'number' } })
        expect(validateField(cpus, 0)).toBe('cpus must be greater than 0')
        expect(validateField(cpus, 0.5)).toBeNull()
    })

    test('a string that does not match the pattern says which pattern', () => {
        const name = only({ pipeline: { $ref: '#/$defs/EntityName' } })
        expect(validateField(name, 'Not A Name')).toContain('does not match')
        expect(validateField(name, 'daily-report')).toBeNull()
    })

    test('a pattern this engine cannot read refuses nothing rather than everything', () => {
        // A python-flavoured named group, which is what a plugin written against `re` may ship.
        const odd = only({ odd: { pattern: '(?P<year>\\d{4})', type: 'string' } })
        expect(validateField(odd, 'anything')).toBeNull()
    })

    test('a value of the wrong shape is named as the shape it should be', () => {
        expect(validateField(required, 7)).toBe('from must be text')
        expect(validateField(depth, 'five')).toBe('max_depth must be a number')
        expect(validateField(only({ pull: { type: 'boolean' } }), 'yes')).toBe('pull must be true or false')
    })

    describe('a union takes either of its shapes', () => {
        // storage.exists min_size, which is a `Size`: a humane string or a count of bytes.
        const size = only({
            min_size: {
                anyOf: [
                    { type: 'string', pattern: '^\\d+(?:\\.\\d+)?(?:[TtGgMmKk]?[Ii]?[Bb])?$' },
                    { type: 'integer', minimum: 0 },
                ],
                default: '0b',
            },
        })

        // REVERT-PROOF. Validate a union as only the branch it is edited as, and the
        // integer a stored document legitimately carries is refused as "text".
        test('an integer a document stored satisfies the integer branch', () => {
            expect(validateField(size, 1)).toBeNull()
        })

        test('a humane string satisfies the string branch, and bare digits are bytes', () => {
            expect(validateField(size, '512kb')).toBeNull()
            expect(validateField(size, '1')).toBeNull()
        })

        test('a value no branch takes is told off by the branch of its own type', () => {
            expect(validateField(size, 'a lot')).toContain('does not match')
            expect(validateField(size, -3)).toBe('min_size must be at least 0')
        })

        test('a value of no branch type names every shape the union takes', () => {
            expect(validateField(size, true)).toBe('min_size must be text or a whole number')
        })
    })

    test('anything at all is a JSON field', () => {
        const body = only({ body: { $ref: '#/$defs/JsonValue' } })
        expect(validateField(body, [1, 2, 3])).toBeNull()
    })

    test('a whole form answers with a problem per field that has one', () => {
        expect(validateFields([required, depth], { max_depth: 99 })).toEqual({
            from: 'from is required',
            max_depth: 'max_depth must be at most 32',
        })
        expect(validateFields([required, depth], { from: 'json', max_depth: 3 })).toEqual({})
    })
})

describe('an enum that is not made of strings', () => {
    const retries = only({ retries: { enum: [0, 1, 3], type: 'integer' } })
    const strict = only({ strict: { enum: [true, false] } })

    test('an integer enum carries the numbers it will submit', () => {
        expect(retries.kind).toBe('select')
        expect(retries.options).toEqual([
            { value: 0, label: '0' },
            { value: 1, label: '1' },
            { value: 3, label: '3' },
        ])
    })

    test('a boolean enum carries the booleans it will submit', () => {
        expect(strict.options).toEqual([
            { value: true, label: 'true' },
            { value: false, label: 'false' },
        ])
    })

    test('a number the document carries is the choice a select draws as chosen', () => {
        // The control matches by JSON, so 1 from an integer enum is not left showing unset.
        expect(retries.options.find((option) => sameJson(option.value, 1))).toEqual({ value: 1, label: '1' })
        expect(retries.options.find((option) => sameJson(option.value, '1'))).toBeUndefined()
        expect(strict.options.find((option) => sameJson(option.value, false))).toEqual({
            value: false,
            label: 'false',
        })
    })

    test('a number the document carries is one of the choices, and its text is not', () => {
        expect(validateField(retries, 3)).toBeNull()
        expect(validateField(retries, '3')).toBe('retries must be one of 0, 1, 3')
        expect(validateField(strict, true)).toBeNull()
        expect(validateField(strict, 'true')).toBe('strict must be one of true, false')
    })
})

describe('what an option reads as', () => {
    test('a string option is drawn bare, because the word is what the document carries', () => {
        // http.request.method through HttpMethod.
        const field = only({ method: { $ref: '#/$defs/HttpMethod', default: 'GET' } })
        expect(field.options.map((option) => option.label)).toEqual([
            'GET',
            'POST',
            'PUT',
            'PATCH',
            'DELETE',
            'HEAD',
            'OPTIONS',
        ])
        expect(optionLabel('all_success')).toBe('all_success')
    })

    test('a number, a boolean and null are drawn as the JSON they are', () => {
        expect(
            only({ retries: { enum: [0, 1, 3], type: 'integer' } }).options.map((one) => one.label),
        ).toEqual(['0', '1', '3'])
        expect(optionLabel(1.5)).toBe('1.5')
        expect(optionLabel(true)).toBe('true')
        expect(optionLabel(null)).toBe('null')
    })
})
