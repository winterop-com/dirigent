import { describe, expect, test } from 'vitest'

import type { JsonMap } from '@/lib/api'
import {
    effectiveValue,
    fallbackText,
    fieldsOf,
    inputText,
    maySubmit,
    parseInput,
    validateField,
    sameJson,
    validateFields,
    withUnreadable,
    type FieldDescriptor,
} from '@/lib/schema-form'

/**
 * Every shape in this file is transcribed from a schema the shipped catalog actually publishes.
 *
 * The catalog was surveyed for the distinct property shapes across all fourteen blocks, and
 * each one has a case here: a plain scalar, a bounded number, an enum reached through `$ref`,
 * pydantic's two spellings of optional, a union of two scalars, a list, a map, and a member
 * with no type at all. A block whose config takes a shape none of these cover is a block whose
 * form silently renders the wrong control, so the fallback has a test of its own.
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
        expect(field.hint).toBe('bytes, or a size such as 1mb')
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

    test('a map of strings', () => {
        // docker.run.env
        expect(only({ env: { additionalProperties: { type: 'string' }, type: 'object' } }).kind).toBe('json')
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

describe('what an empty control shows', () => {
    test('a list says the shape it takes, because a bare textarea teaches nothing', () => {
        expect(only({ argv: { items: { type: 'string' }, type: 'array' } }).placeholder).toBe(
            '["one", "two"]',
        )
    })

    test('a map says its shape too', () => {
        expect(only({ env: { additionalProperties: { type: 'string' }, type: 'object' } }).placeholder).toBe(
            '{"key": "value"}',
        )
    })

    test('a declared default is what an empty box submits, so that is what it shows', () => {
        // params-showcase.regions
        const field = only({
            regions: { default: ['east', 'west'], items: { type: 'string' }, type: 'array' },
        })
        expect(field.placeholder).toBe('["east","west"]')
        expect(fallbackText(field)).toBe('["east","west"]')
    })

    test('a scalar default is its own text', () => {
        expect(only({ batch_size: { default: 500, type: 'integer' } }).placeholder).toBe('500')
    })

    test('a field with no default and no shape to state shows nothing', () => {
        expect(only({ from: { type: 'string' } }).placeholder).toBe('')
        expect(fallbackText(only({ from: { type: 'string' } }))).toBeNull()
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
            'method is one of GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS',
        )
        expect(validateField(method, 'POST')).toBeNull()
    })

    test('a number outside its bounds is refused at the bound it broke', () => {
        expect(validateField(depth, 0)).toBe('max_depth is at least 1')
        expect(validateField(depth, 33)).toBe('max_depth is at most 32')
        expect(validateField(depth, 5)).toBeNull()
    })

    test('a fraction where the schema says integer is refused', () => {
        expect(validateField(depth, 2.5)).toBe('max_depth is a whole number')
    })

    test('a value below an exclusive bound is refused at zero, which a minimum would allow', () => {
        const cpus = only({ cpus: { exclusiveMinimum: 0, type: 'number' } })
        expect(validateField(cpus, 0)).toBe('cpus is greater than 0')
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
        expect(validateField(required, 7)).toBe('from is text')
        expect(validateField(depth, 'five')).toBe('max_depth is a number')
        expect(validateField(only({ pull: { type: 'boolean' } }), 'yes')).toBe('pull is true or false')
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
            expect(validateField(size, -3)).toBe('min_size is at least 0')
        })

        test('a value of no branch type names every shape the union takes', () => {
            expect(validateField(size, true)).toBe('min_size is text or a whole number')
        })
    })

    test('anything at all is a JSON field', () => {
        const body = only({ body: { $ref: '#/$defs/JsonValue' } })
        expect(validateField(body, [1, 2, 3])).toBeNull()
    })

    test('a whole form answers with a problem per field that has one', () => {
        expect(validateFields([required, depth], { max_depth: 99 })).toEqual({
            from: 'from is required',
            max_depth: 'max_depth is at most 32',
        })
        expect(validateFields([required, depth], { from: 'json', max_depth: 3 })).toEqual({})
    })
})

describe('reading what somebody typed', () => {
    const text = only({ from: { type: 'string' } })
    const count = only({ max_depth: { type: 'integer' } })
    const body = only({ body: { $ref: '#/$defs/JsonValue' } })

    test('an emptied control removes the key rather than writing an empty string', () => {
        expect(parseInput(text, '')).toEqual({ ok: true, value: undefined })
        expect(parseInput(count, '   ')).toEqual({ ok: true, value: undefined })
    })

    test('a number arrives as a number, not as the text of one', () => {
        expect(parseInput(count, '12')).toEqual({ ok: true, value: 12 })
    })

    test('text that is not a number is refused where it was typed', () => {
        expect(parseInput(count, 'twelve')).toEqual({ ok: false, message: 'max_depth is a number' })
    })

    test('a JSON field is parsed, so a list arrives as a list', () => {
        expect(parseInput(body, '[200, 204]')).toEqual({ ok: true, value: [200, 204] })
    })

    test('JSON that does not parse is refused with what the parser said', () => {
        const parsed = parseInput(body, '{nope')
        expect(parsed.ok).toBe(false)
    })

    test('a control shows a JSON value as JSON and a scalar as itself', () => {
        expect(inputText(body, { a: 1 })).toBe('{\n  "a": 1\n}')
        expect(inputText(text, 'json')).toBe('json')
        expect(inputText(text, undefined)).toBe('')
        expect(inputText(text, null)).toBe('')
    })

    describe('a program, which is several lines and has to survive being one value', () => {
        const program = only({ program: { contentMediaType: 'application/jq', type: 'string' } }, ['program'])
        const written = 'group_by(.region)\n| map({region: .[0].region, total: (map(.count) | add)})'

        test('the lines it was written on reach the document and come back', () => {
            expect(parseInput(program, written)).toEqual({ ok: true, value: written })
            expect(inputText(program, written)).toBe(written)
        })

        test('a trailing newline is part of the program and neither added nor taken away', () => {
            // An apply diffs the document it is given against the stored one, so a newline this
            // form invented would be an edit nobody made.
            expect(parseInput(program, `${written}\n`)).toEqual({ ok: true, value: `${written}\n` })
            expect(inputText(program, `${written}\n`)).toBe(`${written}\n`)
            expect(parseInput(program, written)).toEqual({ ok: true, value: written })
        })

        test('an emptied editor removes the key, the same as any other control', () => {
            expect(parseInput(program, '\n\n')).toEqual({ ok: true, value: undefined })
        })

        test('what it holds is checked as the text it is', () => {
            expect(validateField(program, written)).toBeNull()
            expect(validateField(program, 12)).toBe('program is text')
            expect(validateField(program, undefined)).toBe('program is required')
        })
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
        expect(validateField(retries, '3')).toBe('retries is one of 0, 1, 3')
        expect(validateField(strict, true)).toBeNull()
        expect(validateField(strict, 'true')).toBe('strict is one of true, false')
    })
})

describe('what a control shows for a field the document does not carry', () => {
    const pull = only({ pull: { default: true, type: 'boolean' } })
    const quiet = only({ quiet: { default: false, type: 'boolean' } })

    test('an omitted field shows the default the server would fill in', () => {
        expect(effectiveValue(pull, undefined)).toBe(true)
        expect(effectiveValue(quiet, undefined)).toBe(false)
    })

    test('a value the document carries is what is shown, default or not', () => {
        expect(effectiveValue(pull, false)).toBe(false)
        expect(effectiveValue(quiet, true)).toBe(true)
    })
})

describe('whether what is on a form may be sent', () => {
    const nothing: ReadonlySet<string> = new Set()

    test('a form with no problem and nothing unreadable may be sent', () => {
        expect(maySubmit({}, nothing)).toBe(true)
    })

    test('a value the schema refuses shuts it', () => {
        expect(maySubmit({ from: 'from is required' }, nothing)).toBe(false)
    })

    test('a box holding text that is not a value shuts it, though every value still parsed', () => {
        expect(maySubmit({}, new Set(['headers']))).toBe(false)
    })

    test('a field that reads again lifts what it put there', () => {
        const held = withUnreadable(nothing, 'headers', 'Unexpected end of JSON input')
        expect(maySubmit({}, held)).toBe(false)
        expect(maySubmit({}, withUnreadable(held, 'headers', null))).toBe(true)
    })

    test('a set that would not change is the set that was passed in', () => {
        const held = withUnreadable(nothing, 'headers', 'that is not JSON')
        expect(withUnreadable(held, 'headers', 'that is not JSON either')).toBe(held)
        expect(withUnreadable(nothing, 'headers', null)).toBe(nothing)
    })
})
