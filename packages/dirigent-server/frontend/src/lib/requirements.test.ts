import { describe, expect, test } from 'vitest'

import type { JsonMap } from '@/lib/api'
import {
    anythingUnmet,
    blockMissing,
    connectionMissing,
    connectionsNamed,
    requiredBlocks,
    requiredPipelines,
    requiredSchemas,
    schemaMissing,
    stepMissing,
    unmetIn,
    unmetLines,
} from '@/lib/requirements'

/** A document naming two blocks and one connection, which is the shape every case here bends. */
const DOCUMENT: JsonMap = {
    name: 'nightly',
    requires: {
        blocks: ['http.get', 'acme.orders'],
        connections: ['acme-prod'],
        pipelines: ['upstream'],
        schemas: ['order-shape'],
    },
    steps: {
        fetch: { block: 'http.get', config: { url: 'https://example.test' } },
        push: { block: 'acme.orders', depends_on: ['fetch'], config: { connection: 'acme-prod' } },
    },
}

const EVERYTHING = ['http.get', 'acme.orders']

describe('what a document names', () => {
    test('reads the blocks it requires of an instance', () => {
        expect(requiredBlocks(DOCUMENT)).toEqual(['http.get', 'acme.orders'])
    })

    test('reads the pipelines it requires, which nothing here can check', () => {
        expect(requiredPipelines(DOCUMENT)).toEqual(['upstream'])
    })

    test('reads the schemas it requires, which is what a copy of a starter names', () => {
        expect(requiredSchemas(DOCUMENT)).toEqual(['order-shape'])
    })

    test('reads a connection a step reaches even where the document forgot to require it', () => {
        const forgot: JsonMap = {
            steps: { push: { block: 'acme.orders', config: { connection: 'sneaky' } } },
        }
        expect(connectionsNamed(forgot)).toEqual(['sneaky'])
    })

    test('names a connection once however many steps reach it', () => {
        const twice: JsonMap = {
            requires: { connections: ['shared'] },
            steps: {
                a: { block: 'http.get', config: { connection: 'shared' } },
                b: { block: 'http.get', config: { connection: 'shared' } },
            },
        }
        expect(connectionsNamed(twice)).toEqual(['shared'])
    })

    test('reads the connection a webhook signature is checked with, which is reached the same way', () => {
        const signed: JsonMap = { steps: { hook: { block: 'http.get', config: { sign_with: 'hmac-key' } } } }
        expect(connectionsNamed(signed)).toEqual(['hmac-key'])
    })
})

describe('what an instance has not got', () => {
    test('is nothing at all when it has everything', () => {
        const unmet = unmetIn(DOCUMENT, EVERYTHING, ['acme-prod'], ['order-shape'])
        expect(anythingUnmet(unmet)).toBe(false)
        expect(unmetLines(unmet)).toEqual([])
    })

    /**
     * THIS IS THE ONE THE FEATURE IS FOR. A step whose block the catalog does not publish is the
     * run that will stop at that step, and it has to be named with the step -- "not installed"
     * on its own is a fact nobody can act on. Breaking the catalog lookup fails here.
     */
    test('names the step and the block when the catalog does not publish it', () => {
        const unmet = unmetIn(DOCUMENT, ['http.get'], ['acme-prod'], ['order-shape'])
        expect(unmet.steps).toEqual([{ step: 'push', block: 'acme.orders' }])
        expect(stepMissing(unmet, 'push')).toBe(true)
        expect(stepMissing(unmet, 'fetch')).toBe(false)
        expect(unmetLines(unmet)).toContain('this run will fail at push: acme.orders is not installed')
    })

    test('marks the required block critical as well as the step that runs it', () => {
        const unmet = unmetIn(DOCUMENT, ['http.get'], ['acme-prod'], ['order-shape'])
        expect(blockMissing(unmet, 'acme.orders')).toBe(true)
        expect(blockMissing(unmet, 'http.get')).toBe(false)
    })

    test('says a required block once even though a step runs it, rather than twice over', () => {
        const lines = unmetLines(unmetIn(DOCUMENT, ['http.get'], ['acme-prod'], ['order-shape']))
        expect(lines.filter((line) => line.includes('acme.orders'))).toHaveLength(1)
    })

    test('says a required block no step runs, because an apply will still refuse it', () => {
        const idle: JsonMap = { requires: { blocks: ['ghost.block'] }, steps: {} }
        const unmet = unmetIn(idle, EVERYTHING, [], [])
        expect(unmet.blocks).toEqual(['ghost.block'])
        expect(unmetLines(unmet)).toEqual(['this document requires ghost.block, which is not installed'])
    })

    /**
     * THIS IS THE COPY OF A STARTER. `dg pipeline new` and the Examples screen both lift a
     * carried `schemas:` into `requires.schemas`, so a document that came that way names shapes
     * nothing has stored; without this the editor says nothing and the run is where it is found.
     */
    test('says a required schema this instance does not hold', () => {
        const unmet = unmetIn(DOCUMENT, EVERYTHING, ['acme-prod'], [])
        expect(schemaMissing(unmet, 'order-shape')).toBe(true)
        expect(anythingUnmet(unmet)).toBe(true)
        expect(unmetLines(unmet)).toEqual(['the schema order-shape is not stored on this instance'])
    })

    test('says nothing about a schema while that listing has not been read', () => {
        const unmet = unmetIn(DOCUMENT, EVERYTHING, ['acme-prod'], null)
        expect(unmet.schemas).toEqual([])
        expect(anythingUnmet(unmet)).toBe(false)
    })

    test('says a named connection this instance does not hold', () => {
        const unmet = unmetIn(DOCUMENT, EVERYTHING, [], ['order-shape'])
        expect(connectionMissing(unmet, 'acme-prod')).toBe(true)
        expect(unmetLines(unmet)).toEqual(['the connection acme-prod is not configured on this instance'])
    })

    test('claims nothing while the catalog has not been read, because unread is not empty', () => {
        const unmet = unmetIn(DOCUMENT, null, null, null)
        expect(anythingUnmet(unmet)).toBe(false)
        expect(unmet.steps).toEqual([])
        expect(unmet.blocks).toEqual([])
        expect(unmet.connections).toEqual([])
        expect(unmet.schemas).toEqual([])
    })

    test('checks the half it has been told about when only one read has landed', () => {
        const unmet = unmetIn(DOCUMENT, null, [], null)
        expect(unmet.steps).toEqual([])
        expect(unmet.connections).toEqual(['acme-prod'])
    })

    test('holds no opinion about a required pipeline, which is not this instance to answer for', () => {
        const unmet = unmetIn(DOCUMENT, EVERYTHING, ['acme-prod'], ['order-shape'])
        expect(anythingUnmet(unmet)).toBe(false)
    })

    test('says nothing at all about a document nobody has loaded', () => {
        expect(anythingUnmet(unmetIn(null, EVERYTHING, [], []))).toBe(false)
    })

    test('leaves a step that names no block alone, which is the document being wrong differently', () => {
        const blockless: JsonMap = { steps: { orphan: { depends_on: [] } } }
        expect(unmetIn(blockless, EVERYTHING, [], []).steps).toEqual([])
    })

    test('keeps the steps in the order the document declares them', () => {
        const both: JsonMap = {
            steps: { first: { block: 'gone.a' }, second: { block: 'gone.b' } },
        }
        expect(unmetIn(both, EVERYTHING, [], []).steps.map((one) => one.step)).toEqual(['first', 'second'])
    })
})
