import { validate } from '@winterop-com/sokkel-ui/schema/validate'
import { beforeAll, describe, expect, test } from 'vitest'

import type { JsonMap } from '@/lib/api'
import { refusalsOf } from '@/lib/form-refusals'
import { formSchema } from '@/lib/form-schema'
import { registerDirigentFormats } from '@/lib/schema-formats'
import { RETRY_SCHEMA, STEP_SCHEMA } from '@/lib/step-keys'

/**
 * The refusals are read from the check the form's own controls run, so these tests run that
 * check: the library's `validate`, with dirigent's formats registered, over the schema the form
 * is handed.
 */
beforeAll(() => {
    registerDirigentFormats()
})

/** `Size` as the catalog writes it: a humane string or a count of bytes. */
const SIZE: JsonMap = {
    anyOf: [
        { pattern: '^\\d+(?:\\.\\d+)?(?:[TtGgMmKk]?[Ii]?[Bb])?$', type: 'string' },
        { minimum: 0, type: 'integer' },
    ],
    format: 'size',
}

/** One closed config schema, as every block publishes one, drawn the way a form draws it. */
function configOf(properties: JsonMap, required: string[] = []) {
    return formSchema({
        $defs: { Size: SIZE, HttpMethod: { enum: ['GET', 'POST'], type: 'string' } },
        additionalProperties: false,
        type: 'object',
        properties,
        ...(required.length > 0 ? { required } : {}),
    })
}

function refused(
    properties: JsonMap,
    value: JsonMap,
    options: { required?: string[]; deferred?: boolean } = {},
) {
    return refusalsOf(validate, configOf(properties, options.required), value, {
        deferred: options.deferred,
        whole: 'config',
    })
}

describe('what a value is refused for', () => {
    test('a required field with nothing in it is named as required', () => {
        expect(refused({ from: { type: 'string' } }, {}, { required: ['from'] })).toEqual({
            from: 'from is required',
        })
    })

    test('a choice outside the enum names the choices', () => {
        expect(refused({ method: { $ref: '#/$defs/HttpMethod' } }, { method: 'TRACE' })).toEqual({
            method: 'method must be one of GET, POST',
        })
        expect(refused({ method: { $ref: '#/$defs/HttpMethod' } }, { method: 'POST' })).toEqual({})
    })

    test('a number outside its bounds says the bound', () => {
        const depth = { max_depth: { maximum: 32, minimum: 1, type: 'integer' } }
        expect(refused(depth, { max_depth: 0 })).toEqual({ max_depth: 'max_depth must be at least 1' })
        expect(refused(depth, { max_depth: 33 })).toEqual({ max_depth: 'max_depth must be at most 32' })
        expect(refused(depth, { max_depth: 2.5 })).toEqual({ max_depth: 'max_depth must be a whole number' })
        expect(refused({ cpus: { exclusiveMinimum: 0, type: 'number' } }, { cpus: 0 })).toEqual({
            cpus: 'cpus must be greater than 0',
        })
    })

    test('a value of the wrong type says the type it must be', () => {
        expect(refused({ from: { type: 'string' } }, { from: 7 })).toEqual({ from: 'from must be text' })
        expect(refused({ pull: { type: 'boolean' } }, { pull: 'yes' })).toEqual({
            pull: 'pull must be true or false',
        })
    })

    test('a key the closed schema does not take is named', () => {
        expect(refused({ from: { type: 'string' } }, { form: 'json' })).toEqual({
            form: 'form is not a field this takes',
        })
    })

    test('an entry of a map is named by the key that carries it', () => {
        const env = { env: { additionalProperties: { type: 'string' }, type: 'object' } }
        expect(refused(env, { env: { PATH: 3 } })).toEqual({ env: 'env.PATH must be text' })
        expect(refused(env, { env: { PATH: '/usr/bin' } })).toEqual({})
    })
})

describe('a union takes any of its shapes', () => {
    test('a size is a humane string or a count of bytes', () => {
        const size = { min_size: { $ref: '#/$defs/Size' } }
        expect(refused(size, { min_size: 1 })).toEqual({})
        expect(refused(size, { min_size: '512kb' })).toEqual({})
        expect(refused(size, { min_size: -3 })).toEqual({ min_size: 'min_size must be at least 0' })
    })

    // REVERT-PROOF. The client's own validator took a union as its first branch's options, so a
    // choice of a later enum branch was listed as refused while the control accepted it.
    test('a choice of an enum that is not the first branch is a value it takes', () => {
        const workers = { workers: { anyOf: [{ type: 'integer', minimum: 1 }, { enum: ['auto', 'off'] }] } }
        expect(refused(workers, { workers: 'auto' })).toEqual({})
        expect(refused(workers, { workers: 4 })).toEqual({})
        expect(Object.keys(refused(workers, { workers: 'many' }))).toEqual(['workers'])
    })
})

describe('a value written as a reference', () => {
    const rows = { rows: { maximum: 1000, minimum: 0, type: 'integer' } }

    test('is left alone in a document, the way the server defers it', () => {
        expect(refused(rows, { rows: '${params.rows}' }, { deferred: true })).toEqual({})
        expect(
            refused(
                { name: { pattern: '^[a-z]+$', type: 'string' } },
                { name: '${params.tenant}-x' },
                {
                    deferred: true,
                },
            ),
        ).toEqual({})
    })

    test('is checked like any other text where the values are not a document', () => {
        expect(refused(rows, { rows: '${params.rows}' })).toEqual({ rows: 'rows must be a whole number' })
    })

    test('the escape is a literal, so it is checked as text', () => {
        expect(
            refused(
                { name: { pattern: '^[a-z]+$', type: 'string' } },
                { name: '$${params.child}' },
                { deferred: true },
            ),
        ).toEqual({ name: 'name does not match ^[a-z]+$' })
    })
})

describe('the step and retry members', () => {
    const steps = formSchema(STEP_SCHEMA)
    const retry = formSchema(RETRY_SCHEMA)

    // REVERT-PROOF. The list beside the step form was judged by a validator of its own that
    // passed any text as a duration, while the control refused it by its format: one field, two
    // verdicts.
    test('a duration the control refuses is refused in the list too', () => {
        expect(refusalsOf(validate, steps, { timeout: 'five minutes' }, { whole: 'step' })).toEqual({
            timeout: 'timeout must be a duration such as 30s or 5m',
        })
        expect(refusalsOf(validate, steps, { timeout: '5m' }, { whole: 'step' })).toEqual({})
    })

    test('a retry budget outside the policy bounds is refused', () => {
        expect(refusalsOf(validate, retry, { max_attempts: 101, jitter: 2 }, { whole: 'retry' })).toEqual({
            max_attempts: 'max_attempts must be at most 100',
            jitter: 'jitter must be at most 1',
        })
    })
})
