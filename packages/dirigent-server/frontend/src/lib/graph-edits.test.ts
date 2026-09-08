import { beforeEach, describe, expect, test } from 'vitest'

import type { JsonMap } from '@/lib/api'
import { cycleRefusal, cycleThrough, withEdge, withoutEdge, withoutStep } from '@/lib/graph-edits'
import {
    changeDocument,
    dependsOn,
    documentStore,
    editsIn,
    edgesIn,
    forgetDocument,
    loadDocument,
    stepNames,
} from '@/lib/pipeline-document'

/** A chain: parse, then active, then report. */
const CHAIN: JsonMap = {
    name: 'chain',
    steps: {
        parse: { block: 'convert.std' },
        active: { block: 'filter.std', depends_on: ['parse'] },
        report: { block: 'render.std', depends_on: ['active'] },
    },
}

/** Two steps with nothing between them, which is what a drag on the canvas joins. */
const APART: JsonMap = {
    name: 'apart',
    steps: { fetch: { block: 'http.get' }, report: { block: 'render.std' } },
}

function copy(document: JsonMap): JsonMap {
    return JSON.parse(JSON.stringify(document)) as JsonMap
}

describe('the loop an edge would close', () => {
    test('is nothing for an edge that only adds a step to the chain', () => {
        expect(cycleThrough(CHAIN, 'parse', 'report')).toBeNull()
    })

    test('is the step itself for a step made to wait for itself', () => {
        expect(cycleThrough(CHAIN, 'parse', 'parse')).toEqual(['parse', 'parse'])
    })

    test('is the pair for an edge drawn back the way it came', () => {
        // parse already feeds active, so active feeding parse closes the shortest loop there is.
        expect(cycleThrough(CHAIN, 'active', 'parse')).toEqual(['parse', 'active', 'parse'])
    })

    test('is the whole chain for a loop closed through steps in between', () => {
        // REVERT-PROOF: a detector that only looked at the step's own `depends_on` would let
        // report feed parse, and the apply would then refuse a document the canvas accepted.
        expect(cycleThrough(CHAIN, 'report', 'parse')).toEqual(['parse', 'active', 'report', 'parse'])
    })

    test('is the shortest loop, because a message naming forty steps names none of them', () => {
        const diamond: JsonMap = {
            steps: {
                a: { block: 'x' },
                b: { block: 'x', depends_on: ['a'] },
                c: { block: 'x', depends_on: ['b'] },
                d: { block: 'x', depends_on: ['a', 'c'] },
            },
        }
        expect(cycleThrough(diamond, 'd', 'a')).toEqual(['a', 'd', 'a'])
    })

    test('is named in the refusal, so the reader is told which steps close it', () => {
        const cycle = cycleThrough(CHAIN, 'report', 'parse')
        expect(cycle).not.toBeNull()
        expect(cycleRefusal('report', 'parse', cycle as string[])).toBe(
            'parse cannot wait for report: that closes a loop, parse → active → report → parse',
        )
    })

    test('is nothing in a document with no edges at all', () => {
        expect(cycleThrough(APART, 'fetch', 'report')).toBeNull()
    })
})

describe('an edge, as the document holds it', () => {
    test('is a prerequisite on the step that waits', () => {
        const joined = withEdge(APART, 'fetch', 'report')
        expect(dependsOn(joined, 'report')).toEqual(['fetch'])
        // The document it was given is untouched: the store holds a copy, and an edit builds one.
        expect(dependsOn(APART, 'report')).toEqual([])
    })

    test('is the same document again when it is already there', () => {
        const joined = withEdge(APART, 'fetch', 'report')
        expect(withEdge(joined, 'fetch', 'report')).toBe(joined)
    })

    test('leaves the other prerequisites where they were when it is taken away', () => {
        const both = withEdge(withEdge(APART, 'fetch', 'report'), 'report', 'fetch')
        const cut = withoutEdge(both, 'fetch', 'report')
        expect(dependsOn(cut, 'report')).toEqual([])
        expect(dependsOn(cut, 'fetch')).toEqual(['report'])
    })

    test('is the same document again when it was never there', () => {
        expect(withoutEdge(APART, 'fetch', 'report')).toBe(APART)
    })

    test('takes the key off the step entirely when it was the last one', () => {
        const joined = withEdge(APART, 'fetch', 'report')
        const steps = withoutEdge(joined, 'fetch', 'report').steps as Record<string, JsonMap>
        expect(steps.report).not.toHaveProperty('depends_on')
    })
})

describe('drawing and deleting an edge through the store', () => {
    beforeEach(() => {
        forgetDocument()
        loadDocument('apart', copy(APART))
    })

    test('counts as one unapplied edit, on the step that waits', () => {
        changeDocument((current) => withEdge(current, 'fetch', 'report'))
        const state = documentStore.get()
        const edits = editsIn(state.applied, state.local)
        expect(edits.steps).toEqual(['report'])
        expect(edits.count).toBe(1)
    })

    test('drawing the same edge twice is one edit, not two', () => {
        changeDocument((current) => withEdge(current, 'fetch', 'report'))
        const once = documentStore.get().local
        changeDocument((current) => withEdge(current, 'fetch', 'report'))
        const twice = documentStore.get().local
        // Nothing changed, so nothing was published: the store still holds the same document.
        expect(twice).toBe(once)
        expect(editsIn(documentStore.get().applied, twice).count).toBe(1)
    })

    test('deleting it puts the document back where it started', () => {
        changeDocument((current) => withEdge(current, 'fetch', 'report'))
        changeDocument((current) => withoutEdge(current, 'fetch', 'report'))
        const state = documentStore.get()
        expect(editsIn(state.applied, state.local).count).toBe(0)
    })

    test('is refused while the source pane holds text that is not a document', () => {
        documentStore.set({ ...documentStore.get(), draft: 'steps: [', parseError: 'bad' })
        expect(changeDocument((current) => withEdge(current, 'fetch', 'report'))).toBe(false)
        expect(dependsOn(documentStore.get().local, 'report')).toEqual([])
    })
})

describe('a document without one step', () => {
    /** A fan-in: report waits for both halves, so taking one out edits the other half's list. */
    const FAN_IN: JsonMap = {
        name: 'fan-in',
        steps: {
            parse: { block: 'convert.std' },
            left: { block: 'filter.std', depends_on: ['parse'] },
            right: { block: 'filter.std', depends_on: ['parse'] },
            report: { block: 'render.std', depends_on: ['left', 'right'] },
        },
    }

    test('no longer declares it', () => {
        expect(stepNames(withoutStep(copy(FAN_IN), 'left'))).toEqual(['parse', 'right', 'report'])
    })

    test('takes its name out of every other step that waited for it', () => {
        // REVERT-PROOF: a `depends_on` naming a step the document no longer declares is what
        // `$apply` refuses, so the deletion is one edit rather than two.
        const left = withoutStep(copy(FAN_IN), 'left')
        expect(dependsOn(left, 'report')).toEqual(['right'])
        expect(edgesIn(left)).toEqual([
            ['parse', 'right'],
            ['right', 'report'],
        ])
    })

    test('drops the list entirely where the step was the only thing in it', () => {
        const left = withoutStep(copy(FAN_IN), 'parse')
        expect(dependsOn(left, 'left')).toEqual([])
        expect(left.steps).toEqual({
            left: { block: 'filter.std' },
            right: { block: 'filter.std' },
            report: { block: 'render.std', depends_on: ['left', 'right'] },
        })
    })

    test('is the document it was given for a step the document has not got', () => {
        const held = copy(FAN_IN)
        expect(withoutStep(held, 'nothing')).toBe(held)
    })

    test('is one unapplied edit, the way every other gesture on the canvas is', () => {
        loadDocument('chain', copy(CHAIN))
        expect(changeDocument((current) => withoutStep(current, 'active'))).toBe(true)
        const state = documentStore.get()
        expect(stepNames(state.local)).toEqual(['parse', 'report'])
        expect(dependsOn(state.local, 'report')).toEqual([])
        expect(editsIn(state.applied, state.local).count).toBeGreaterThan(0)
    })
})
