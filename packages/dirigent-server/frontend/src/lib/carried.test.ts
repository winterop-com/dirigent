import { describe, expect, test } from 'vitest'

import type { JsonMap, Problem } from '@/lib/api'
import {
    actionWord,
    anythingCarried,
    carriedCodes,
    carriedItems,
    carriedRefusal,
    creations,
    offerBlocked,
    connectionNote,
    mayUpdate,
    missingConnections,
    offerNote,
    sameJson,
    type Held,
} from '@/lib/carried'

/** The two shapes the document below carries, which every case here compares against. */
const CATALOGUE: JsonMap = { type: 'object', required: ['day'] }
const REGION: JsonMap = { type: 'object', required: ['region'] }

/** A document carrying both sections, which is the shape every case here bends. */
const DOCUMENT: JsonMap = {
    code: 'nightly-regional-load',
    schemas: { 'nightly-catalogue': CATALOGUE, 'nightly-region': REGION },
    connections: {
        'ops-receiver': { kind: 'http', config: { base_url: 'http://127.0.0.1', hmac_secret: 'shh' } },
    },
    steps: {},
}

/** A document carrying only schemas, which is the one the offer can finish on its own. */
const SCHEMAS_ONLY: JsonMap = { schemas: { 'order-shape': { type: 'object' } } }

const NOTHING_HELD: Held = { schemas: [], connections: [] }

/** Every code held, and every schema holding exactly what the document carries. */
const EVERYTHING_HELD: Held = {
    schemas: [
        { code: 'nightly-catalogue', body: CATALOGUE, used_by: [] },
        { code: 'nightly-region', body: REGION, used_by: [] },
    ],
    connections: ['ops-receiver'],
}

/** A refusal in the shape the apply route makes one: the sentence, and the issue behind it. */
function refusal(code: string): Problem {
    return {
        status: 422,
        title: 'Unprocessable Content',
        detail: 'this document carries its own schemas',
        code: 'document.refused',
        params: {},
        problems: [{ code, message: 'carried', params: {}, location: null }],
        instance: null,
    }
}

describe('which refusal this answers', () => {
    test('recognises the one a carried schemas section makes', () => {
        expect(carriedRefusal(refusal('document.carried_schemas'))).toBe(true)
    })

    test('recognises the one a carried connections section makes', () => {
        expect(carriedRefusal(refusal('document.carried_connections'))).toBe(true)
    })

    test('leaves every other refusal alone, because there is nothing here to offer for one', () => {
        expect(carriedRefusal(refusal('document.unsatisfied'))).toBe(false)
        expect(carriedRefusal(null)).toBe(false)
    })
})

describe('what a document carries', () => {
    test('is nothing at all for a document that names rather than carries', () => {
        expect(anythingCarried({ requires: { schemas: ['nightly-region'] } })).toBe(false)
    })

    test('is both sections when it carries both', () => {
        expect(anythingCarried(DOCUMENT)).toBe(true)
    })

    test('names the codes the instance is asked about, which is what the document carries', () => {
        expect(carriedCodes(DOCUMENT)).toEqual({
            schemas: ['nightly-catalogue', 'nightly-region'],
            connections: ['ops-receiver'],
        })
    })

    test('names every entry, the schemas first, in the order the document writes them', () => {
        const items = carriedItems(DOCUMENT, NOTHING_HELD, true)
        expect(items.map((one) => `${one.kind} ${one.code}`)).toEqual([
            'schema nightly-catalogue',
            'schema nightly-region',
            'connection ops-receiver',
        ])
    })
})

describe('the four cases a carried entry meets', () => {
    /**
     * ONE: the instance has nothing under that code, so the document is what it is created
     * from -- and under the key the document addresses it by, which is what every
     * `validate.schema` step in it references. Nothing generates a code here.
     */
    test('creates a carried schema the instance has nothing under', () => {
        const made = creations(carriedItems(DOCUMENT, NOTHING_HELD, true))
        expect(made.map((one) => one.code)).toEqual(['nightly-catalogue', 'nightly-region'])
        expect(made[0]?.body).toEqual(CATALOGUE)
    })

    /** TWO: the same thing is already there, so there is nothing to do and applying is safe. */
    test('leaves a carried schema the instance already holds the same body for', () => {
        const items = carriedItems(DOCUMENT, EVERYTHING_HELD, true)
        expect(items.map((one) => one.action)).toEqual(['held', 'held', 'held'])
        expect(creations(items)).toEqual([])
        expect(offerBlocked(items)).toBeUndefined()
    })

    test('reads the same body through a different key order as the same body', () => {
        const held: Held = {
            schemas: [{ code: 'order-shape', body: { title: 'x', type: 'object' }, used_by: [] }],
            connections: [],
        }
        const carried: JsonMap = { schemas: { 'order-shape': { type: 'object', title: 'x' } } }
        expect(carriedItems(carried, held, true)[0]?.action).toBe('held')
    })

    /**
     * THREE: the codes collide and the bodies do not. Applying would bind this pipeline's gate
     * to the instance's shape rather than the one written in the document, so the apply is shut
     * and the row carries the write that settles it.
     */
    test('calls a carried schema the instance holds something else under a difference', () => {
        const held: Held = {
            schemas: [{ code: 'nightly-region', body: { type: 'string' }, used_by: [] }],
            connections: ['ops-receiver'],
        }
        const items = carriedItems(DOCUMENT, held, true)
        expect(items.find((one) => one.code === 'nightly-region')?.action).toBe('differs')
        expect(creations(items).map((one) => one.code)).toEqual(['nightly-catalogue'])
    })

    test('shuts the button on a difference, naming the code and what else reads it', () => {
        const held: Held = {
            schemas: [{ code: 'nightly-region', body: { type: 'string' }, used_by: [] }],
            connections: ['ops-receiver'],
        }
        const why = offerBlocked(carriedItems(DOCUMENT, held, true))
        expect(why).toContain('nightly-region')
        expect(why).toContain('Every pipeline naming that code')
    })

    test('carries both shapes on the row, so the collision can be shown and replaced', () => {
        const stored = { type: 'string' }
        const held: Held = { schemas: [{ code: 'nightly-region', body: stored, used_by: [] }], connections: [] }
        const row = carriedItems(DOCUMENT, held, true).find((one) => one.code === 'nightly-region')
        expect(row?.body).toEqual(REGION)
        expect(row?.stored).toEqual(stored)
    })

    test('carries the pipelines naming the stored code, so a replacement names who it is for', () => {
        const held: Held = {
            schemas: [{ code: 'nightly-region', body: { type: 'string' }, used_by: ['audited'] }],
            connections: [],
        }
        const row = carriedItems(DOCUMENT, held, true).find((one) => one.code === 'nightly-region')
        expect(row?.action).toBe('differs')
        // The document being applied need not be among them, which is why the write stands alone.
        expect(row?.usedBy).toEqual(['audited'])
    })

    /**
     * The row's own control is drawn only where pressing it would do something: a collision
     * over a schema, with the shape to write and the shape being replaced both in hand.
     */
    test('offers the update on a collision and on nothing else', () => {
        const held: Held = {
            schemas: [{ code: 'nightly-region', body: { type: 'string' }, used_by: [] }],
            connections: ['ops-receiver'],
        }
        const offered = carriedItems(DOCUMENT, held, true).filter(mayUpdate)
        expect(offered.map((one) => one.code)).toEqual(['nightly-region'])
    })

    test('offers it on nothing where every code agrees or is absent', () => {
        expect(carriedItems(DOCUMENT, EVERYTHING_HELD, true).some(mayUpdate)).toBe(false)
        expect(carriedItems(DOCUMENT, NOTHING_HELD, true).some(mayUpdate)).toBe(false)
    })

    /**
     * FOUR is not this module's: a document that only names a code under `requires:` carries
     * nothing to create from, and the apply's own issues and `lib/requirements` say it.
     */
    test('has nothing to say about a document that names rather than carries', () => {
        const naming: JsonMap = { requires: { schemas: ['order-shape'] } }
        expect(carriedItems(naming, NOTHING_HELD, true)).toEqual([])
        expect(offerBlocked(carriedItems(naming, NOTHING_HELD, true))).toBeUndefined()
    })
})

describe('what becomes of a carried connection', () => {
    /**
     * THIS IS THE JUDGEMENT. A connection's config can hold a credential in a field the kind
     * declares secret and in one it does not -- a `sql` url carries a password inline -- so
     * nothing here can say a carried connection holds none. It is never stored.
     */
    test('is never stored, whatever it carries', () => {
        const items = carriedItems(DOCUMENT, NOTHING_HELD, true)
        const connection = items.find((one) => one.kind === 'connection')
        expect(connection?.action).toBe('missing')
        expect(connection?.connectionKind).toBe('http')
        expect(creations(items).some((one) => one.kind === 'connection')).toBe(false)
    })

    test('is the instance own where one is there, which is never compared with the carried one', () => {
        const items = carriedItems(DOCUMENT, EVERYTHING_HELD, true)
        expect(items.find((one) => one.kind === 'connection')?.action).toBe('held')
    })

    test('shuts the button while it is not there, naming it and where to create it', () => {
        const why = offerBlocked(carriedItems(DOCUMENT, NOTHING_HELD, true))
        expect(why).toContain('no connection coded ops-receiver')
    })

    test('names every connection where more than one is missing', () => {
        const two: JsonMap = { connections: { first: { kind: 'http' }, second: { kind: 'sql' } } }
        const why = offerBlocked(carriedItems(two, NOTHING_HELD, true))
        expect(why).toContain('no connections coded first, second')
    })
})

describe('an account that may not store a schema', () => {
    test('stores nothing, and the button says so', () => {
        const items = carriedItems(SCHEMAS_ONLY, NOTHING_HELD, false)
        expect(items.map((one) => one.action)).toEqual(['missing'])
        expect(creations(items)).toEqual([])
        expect(offerBlocked(items)).toContain('only an admin can store one')
    })
})

describe('what the rows and the sentences under them say', () => {
    test('says what each row does in the words the row reads', () => {
        const held: Held = { schemas: [{ code: 'nightly-region', body: REGION, used_by: [] }], connections: [] }
        expect(carriedItems(DOCUMENT, held, true).map(actionWord)).toEqual([
            'create',
            'already here',
            'missing',
        ])
    })

    /**
     * ONE LINE SAYS WHAT THIS IS AND WHAT PRESSING APPLY DOES. The server's own refusal is not
     * drawn beside it: a sentence written for every surface is not a way forward on this one.
     */
    test('states the rule and what applying does, in one line, counting what it stores', () => {
        expect(offerNote(carriedItems(SCHEMAS_ONLY, NOTHING_HELD, true))).toBe(
            'An instance does not store what a document carries. Applying stores the schema marked ' +
                'create, and names every code here under requires.',
        )
    })

    test('says only the naming where it stores nothing', () => {
        expect(offerNote(carriedItems(DOCUMENT, EVERYTHING_HELD, true))).toBe(
            'An instance does not store what a document carries. Applying names every code here under requires.',
        )
    })

    /**
     * THE REASON AND THE REMEDY ARE NOT THE SAME SENTENCE. The note says why a connection is
     * never stored from a document; the control beside it is where one is created, so the
     * dialog never writes out an instruction a button already carries.
     */
    test('say why a connection is not stored without telling anybody where to go', () => {
        const items = carriedItems(DOCUMENT, NOTHING_HELD, true)
        const note = connectionNote(items)
        expect(note).toContain('A connection is not created from a document')
        expect(note).not.toContain('Connections screen')
        expect(missingConnections(items).map((one) => one.code)).toEqual(['ops-receiver'])
    })

    test('say nothing about connections for a document that carries none', () => {
        expect(connectionNote(carriedItems(SCHEMAS_ONLY, NOTHING_HELD, true))).toBeUndefined()
        expect(missingConnections(carriedItems(SCHEMAS_ONLY, NOTHING_HELD, true))).toEqual([])
    })

    test('offers no door for a connection this instance already holds', () => {
        expect(missingConnections(carriedItems(DOCUMENT, EVERYTHING_HELD, true))).toEqual([])
        expect(connectionNote(carriedItems(DOCUMENT, EVERYTHING_HELD, true))).toBeUndefined()
    })
})

describe('comparing two parsed schemas', () => {
    test('ignores the order the keys arrived in, at every depth', () => {
        expect(sameJson({ a: 1, b: { c: 2, d: 3 } }, { b: { d: 3, c: 2 }, a: 1 })).toBe(true)
    })

    test('holds a list to its order, because a required list is one', () => {
        expect(sameJson({ required: ['a', 'b'] }, { required: ['b', 'a'] })).toBe(false)
    })

    test('sees a key one side has and the other has not', () => {
        expect(sameJson({ a: 1 }, { a: 1, b: 2 })).toBe(false)
        expect(sameJson({ a: 1, b: 2 }, { a: 1 })).toBe(false)
    })

    test('separates null from a missing key and from false', () => {
        expect(sameJson({ a: null }, { a: false })).toBe(false)
        expect(sameJson(null, {})).toBe(false)
    })
})
