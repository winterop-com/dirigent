import { beforeEach, describe, expect, test } from 'vitest'

import type { JsonMap } from '@/lib/api'
import {
    applyVariant,
    blockOf,
    changeDocument,
    configOf,
    configSummary,
    dependsOn,
    documentStore,
    edgesIn,
    editsIn,
    editsLabel,
    fanOutOf,
    forgetDocument,
    fromYaml,
    loadDocument,
    NEW_CODE,
    NEW_DOCUMENT,
    newDocument,
    reportIn,
    revertDocument,
    startDocument,
    stepEdited,
    stepHeading,
    stepName,
    stepNames,
    stepTabLabel,
    toYaml,
    withDependsOn,
    withoutReport,
    withReport,
    withStep,
    withStepConfig,
    withStepName,
    writeSource,
} from '@/lib/pipeline-document'

/** A document of the shape `examples/transform` applies: two steps and an edge between them. */
function document(): JsonMap {
    return {
        format: 'dirigent/v1',
        kind: 'pipeline',
        code: 'convert-one',
        name: 'Convert one',
        description: 'Reshape one document.',
        steps: {
            parse: { block: 'convert.std', config: { from: 'json', to: 'yaml', input: '{}' } },
            report: { block: 'transform.jq', depends_on: ['parse'], config: { expression: '.' } },
        },
    }
}

beforeEach(() => {
    forgetDocument()
})

/**
 * A NODE IS TITLED BY THE STEP'S NAME AND KEYED BY ITS KEY.
 *
 * A step's key is what `depends_on`, every attempt and every log line reference, so it never
 * leaves the box: a step that carries a name is titled with it and the key is drawn under it,
 * and a step with no name is titled by the key itself, once.
 */
describe('how a step is headed on the canvas and in its own pane', () => {
    /** The same document, with one step given something to be called. */
    function named(): JsonMap {
        return withStepName(document(), 'parse', 'Parse the upload')
    }

    test('a step with a name is titled with it, over its key', () => {
        expect(stepHeading(named(), 'parse')).toEqual({
            title: 'Parse the upload',
            code: 'parse',
            named: true,
        })
    })

    test('a step with no name is titled by its key, and the key is not drawn twice', () => {
        expect(stepHeading(document(), 'parse')).toEqual({ title: 'parse', code: null, named: false })
    })

    test('a name is read off the step and nothing else is', () => {
        expect(stepName(named(), 'parse')).toBe('Parse the upload')
        expect(stepName(document(), 'parse')).toBeNull()
        expect(stepName(document(), 'nothing')).toBeNull()
    })

    test('emptying the box takes the name out of the document rather than writing an empty one', () => {
        const cleared = withStepName(named(), 'parse', '')
        expect(stepName(cleared, 'parse')).toBeNull()
        expect(cleared.steps).toEqual(document().steps)
        expect(withStepName(named(), 'parse', null).steps).toEqual(document().steps)
    })

    test('a name is trimmed on the way into the document', () => {
        expect(stepName(withStepName(document(), 'parse', '  Parse  '), 'parse')).toBe('Parse')
    })

    test('naming a step is an edit of that step and of nothing else', () => {
        expect(editsIn(document(), named()).steps).toEqual(['parse'])
    })
})

describe('reading a document', () => {
    test('names its steps in the order it declares them', () => {
        expect(stepNames(document())).toEqual(['parse', 'report'])
        expect(stepNames(null)).toEqual([])
    })

    test('says which block each step runs, and what config it carries', () => {
        expect(blockOf(document(), 'parse')).toBe('convert.std')
        expect(blockOf(document(), 'nothing')).toBeNull()
        expect(configOf(document(), 'report')).toEqual({ expression: '.' })
        expect(configOf(document(), 'nothing')).toEqual({})
    })

    test('turns depends_on into edges pointing from prerequisite to dependent', () => {
        expect(edgesIn(document())).toEqual([['parse', 'report']])
        expect(dependsOn(document(), 'report')).toEqual(['parse'])
    })

    test('drops an edge naming a step the document does not declare', () => {
        const broken = withDependsOn(document(), 'report', ['gone'])
        expect(edgesIn(broken)).toEqual([])
    })

    test('summarises the scalars of a config, and says nothing about one with none', () => {
        expect(configSummary({ from: 'json', to: 'yaml' })).toBe('from: json · to: yaml')
        expect(configSummary({ headers: { a: 'b' } })).toBeNull()
        expect(configSummary({})).toBeNull()
    })
})

describe('changing a document', () => {
    test('replaces one step config and leaves every other step alone', () => {
        const changed = withStepConfig(document(), 'parse', { from: 'json', to: 'csv' })
        expect(configOf(changed, 'parse')).toEqual({ from: 'json', to: 'csv' })
        expect(configOf(changed, 'report')).toEqual({ expression: '.' })
        expect(blockOf(changed, 'parse')).toBe('convert.std')
    })

    test('leaves the document it was given untouched, so the applied copy cannot drift', () => {
        const original = document()
        withStepConfig(original, 'parse', { from: 'yaml' })
        expect(configOf(original, 'parse')).toEqual({ from: 'json', to: 'yaml', input: '{}' })
    })

    test('adds a step running one block and depending on nothing', () => {
        const grown = withStep(document(), 'as_csv', 'convert.std')
        expect(stepNames(grown)).toEqual(['parse', 'report', 'as_csv'])
        expect(grown.steps).toMatchObject({ as_csv: { block: 'convert.std' } })
    })

    test('writes prerequisites, and removes the key rather than writing an empty list', () => {
        const joined = withDependsOn(document(), 'parse', ['report'])
        expect(dependsOn(joined, 'parse')).toEqual(['report'])
        const cleared = withDependsOn(joined, 'report', [])
        expect(Object.keys(cleared.steps as JsonMap)).toEqual(['parse', 'report'])
        expect(dependsOn(cleared, 'report')).toEqual([])
    })

    test('says nothing about a step the document does not have', () => {
        expect(withStepConfig(document(), 'nothing', { a: 1 })).toEqual(document())
    })
})

describe('what is unapplied', () => {
    test('is nothing at all when the two documents agree, whatever order their keys are in', () => {
        const applied = document()
        const local = { kind: 'pipeline', format: 'dirigent/v1', ...document() }
        expect(editsIn(applied, local).count).toBe(0)
    })

    test('names the step whose config was edited, and only that step', () => {
        // Breaking this stops the topbar counting and the node wearing its `edited` mark.
        const applied = document()
        const local = withStepConfig(applied, 'parse', { from: 'json', to: 'csv' })
        const edits = editsIn(applied, local)
        expect(edits.steps).toEqual(['parse'])
        expect(edits.count).toBe(1)
        expect(stepEdited(edits, 'parse')).toBe(true)
        expect(stepEdited(edits, 'report')).toBe(false)
    })

    test('counts a step that was added', () => {
        expect(editsIn(document(), withStep(document(), 'as_csv', 'convert.std')).steps).toEqual(['as_csv'])
    })

    test('counts a step that was removed', () => {
        const local = document()
        delete (local.steps as JsonMap).report
        expect(editsIn(document(), local).steps).toEqual(['report'])
    })

    test('counts a change to a top-level field as an edit of its own', () => {
        const local = { ...document(), description: 'Something else.' }
        const edits = editsIn(document(), local)
        expect(edits.fields).toEqual(['description'])
        expect(edits.count).toBe(1)
    })

    test('counts a step and a field together', () => {
        const local = { ...withStepConfig(document(), 'parse', { from: 'csv' }), description: 'Else.' }
        expect(editsIn(document(), local).count).toBe(2)
    })

    test('says how many in the words the chip wears', () => {
        expect(editsLabel({ steps: ['parse'], fields: [], count: 1 })).toBe('1 unapplied edit')
        expect(editsLabel({ steps: ['parse'], fields: ['name'], count: 2 })).toBe('2 unapplied edits')
    })

    test('a pipeline with no stored version yet has every step of it unapplied', () => {
        expect(editsIn(null, document()).count).toBe(2)
    })
})

describe('the document as YAML', () => {
    test('round-trips, so what the source pane writes back is what the graph reads', () => {
        const read = fromYaml(toYaml(document()))
        expect(read.ok).toBe(true)
        if (read.ok) expect(read.document).toEqual(document())
    })

    test('says what the document is before anything else, even when the stored one did not', () => {
        const stored: JsonMap = { code: 'review-dag', kind: 'pipeline', tags: ['review'], steps: {} }
        expect(toYaml(stored).split('\n').slice(0, 3)).toEqual(['format: dirigent/v1', 'kind: pipeline', 'code: review-dag'])
    })

    test('writes the top-level keys in the order the examples use', () => {
        const stored: JsonMap = {
            steps: {},
            params: {},
            tags: ['review'],
            description: 'A graph.',
            name: 'Review DAG',
            code: 'review-dag',
            concurrency: 'allow',
        }
        const keys = toYaml(stored)
            .split('\n')
            .filter((line) => /^[a-z_]+:/.test(line))
            .map((line) => line.split(':')[0])
        expect(keys).toEqual([
            'format',
            'kind',
            'code',
            'name',
            'description',
            'tags',
            'params',
            'steps',
            'concurrency',
        ])
    })

    test('refuses text that is not YAML, saying what the parser said', () => {
        const read = fromYaml('steps:\n  parse: [')
        expect(read.ok).toBe(false)
    })

    test('refuses a document that is not a mapping', () => {
        expect(fromYaml('- one\n- two')).toEqual({
            ok: false,
            message: 'a document is a mapping of keys, not a single value',
        })
        expect(fromYaml('')).toEqual({ ok: false, message: 'the document is empty' })
    })
})

describe('the store the whole screen reads', () => {
    test('starts a pipeline with the applied document as the local one', () => {
        loadDocument('convert-one', document())
        const state = documentStore.get()
        expect(state.code).toBe('convert-one')
        expect(state.local).toEqual(document())
        expect(editsIn(state.applied, state.local).count).toBe(0)
    })

    test('holds the local document apart from the applied one, so an edit does not reach it', () => {
        loadDocument('convert-one', document())
        changeDocument((current) => withStepConfig(current, 'parse', { from: 'csv' }))
        const state = documentStore.get()
        expect(configOf(state.applied, 'parse')).toEqual({ from: 'json', to: 'yaml', input: '{}' })
        expect(configOf(state.local, 'parse')).toEqual({ from: 'csv' })
        expect(editsIn(state.applied, state.local).count).toBe(1)
    })

    test('takes source text as the document when it parses', () => {
        loadDocument('convert-one', document())
        writeSource(toYaml(withStep(document(), 'as_csv', 'convert.std')))
        const state = documentStore.get()
        expect(state.parseError).toBeNull()
        expect(state.draft).toBeNull()
        expect(stepNames(state.local)).toEqual(['parse', 'report', 'as_csv'])
    })

    test('keeps the text and the last good document when the text does not parse', () => {
        loadDocument('convert-one', document())
        writeSource('steps:\n  parse: [')
        const state = documentStore.get()
        expect(state.parseError).not.toBeNull()
        expect(state.draft).toBe('steps:\n  parse: [')
        expect(stepNames(state.local)).toEqual(['parse', 'report'])
    })

    test('refuses an edit from another tab while the source does not parse', () => {
        loadDocument('convert-one', document())
        writeSource('steps:\n  parse: [')
        expect(changeDocument((current) => withStepConfig(current, 'parse', { from: 'csv' }))).toBe(false)
        expect(configOf(documentStore.get().local, 'parse')).toEqual({ from: 'json', to: 'yaml', input: '{}' })
    })

    test('a parse error is cleared by text that parses, and editing resumes', () => {
        loadDocument('convert-one', document())
        writeSource('steps:\n  parse: [')
        writeSource(toYaml(document()))
        expect(documentStore.get().parseError).toBeNull()
        expect(changeDocument((current) => withStepConfig(current, 'parse', { from: 'csv' }))).toBe(true)
    })

    test('reverting throws the edits away and the draft with them', () => {
        loadDocument('convert-one', document())
        writeSource('steps:\n  parse: [')
        revertDocument()
        const state = documentStore.get()
        expect(state.parseError).toBeNull()
        expect(state.local).toEqual(document())
        expect(editsIn(state.applied, state.local).count).toBe(0)
    })

    test('a pipeline with no version yet loads with no document at all', () => {
        loadDocument('brand-new', null)
        expect(documentStore.get().local).toBeNull()
        expect(changeDocument((current) => current)).toBe(false)
    })

    test('forgetting it leaves nothing behind for the next screen', () => {
        loadDocument('convert-one', document())
        forgetDocument()
        expect(documentStore.get()).toEqual({
            code: null,
            applied: null,
            local: null,
            draft: null,
            parseError: null,
        })
    })
})

describe('a document nothing has applied', () => {
    beforeEach(forgetDocument)

    test('starts from a skeleton an apply accepts, with a code to change', () => {
        expect(newDocument()).toEqual({
            format: 'dirigent/v1',
            kind: 'pipeline',
            code: NEW_CODE,
            name: 'My pipeline',
            steps: {},
        })
        expect(stepNames(newDocument())).toEqual([])
    })

    test('is held under the new-document code, with nothing applied behind it', () => {
        startDocument()
        const state = documentStore.get()
        expect(state.code).toBe(NEW_DOCUMENT)
        expect(state.applied).toBeNull()
        expect(state.local).toEqual(newDocument())
        expect(state.parseError).toBeNull()
    })

    test('is edited like any other: the source pane writes it and the graph reads it', () => {
        startDocument()
        writeSource('format: dirigent/v1\nkind: pipeline\ncode: mine\nsteps:\n  one:\n    block: transform.jq\n')
        const state = documentStore.get()
        expect(state.local?.code).toBe('mine')
        expect(stepNames(state.local)).toEqual(['one'])
    })

    test('hands each start a document of its own, so one edit cannot reach the next', () => {
        const first = newDocument()
        first.code = 'edited'
        expect(newDocument().code).toBe(NEW_CODE)
    })
})

describe('what the step tab is called', () => {
    test('is the bare word while nothing is chosen', () => {
        expect(stepTabLabel(null)).toBe('Step')
    })

    test('carries the chosen step key, which is what the document references', () => {
        expect(stepTabLabel('parse')).toBe('Step · parse')
    })

    test('cuts a key too long for the strip rather than widening it', () => {
        const label = stepTabLabel('a-step-with-a-very-long-key')
        expect(label.length).toBeLessThanOrEqual('Step · '.length + 14)
        expect(label.endsWith('…')).toBe(true)
    })

    test('leaves a key that just fits alone', () => {
        expect(stepTabLabel('fourteen_chars')).toBe('Step · fourteen_chars')
    })
})

describe('which button an apply wears', () => {
    test('is quiet where applying would write nothing', () => {
        loadDocument('convert-one', document())
        const state = documentStore.get()
        expect(applyVariant(editsIn(state.applied, state.local), false)).toBe('outline')
    })

    test('is the identity colour the moment the document differs', () => {
        loadDocument('convert-one', document())
        changeDocument((current) => withStepConfig(current, 'parse', { from: 'json', to: 'csv' }))
        const state = documentStore.get()
        expect(applyVariant(editsIn(state.applied, state.local), false)).toBe('default')
    })

    test('is the identity colour on a document nothing has applied, edited or not', () => {
        startDocument()
        const state = documentStore.get()
        expect(editsIn(state.applied, state.local).count).toBe(0)
        expect(applyVariant(editsIn(state.applied, state.local), true)).toBe('default')
    })
})

describe('whether a step fans out', () => {
    const FANNED: JsonMap = {
        steps: {
            once: { block: 'transform.jq' },
            listed: { block: 'transform.jq', for_each: ['north', 'south', 'east'] },
            resolved: { block: 'transform.jq', for_each: '${params.regions}' },
        },
    }

    test('is no for a step that says nothing about it', () => {
        expect(fanOutOf(FANNED, 'once')).toEqual({ fanOut: false, items: null })
        expect(fanOutOf(FANNED, 'nothing')).toEqual({ fanOut: false, items: null })
        expect(fanOutOf(null, 'once')).toEqual({ fanOut: false, items: null })
    })

    test('counts the items where the document writes the list out', () => {
        expect(fanOutOf(FANNED, 'listed')).toEqual({ fanOut: true, items: 3 })
    })

    test('counts nothing where the list is an expression a run resolves', () => {
        expect(fanOutOf(FANNED, 'resolved')).toEqual({ fanOut: true, items: null })
    })
})

describe('the report section', () => {
    test('a document with no section declares none', () => {
        expect(reportIn({ steps: {} })).toEqual({ declared: false, template: null })
        expect(reportIn(null)).toEqual({ declared: false, template: null })
    })

    test('an empty section asks for the built-in document', () => {
        expect(reportIn({ report: {} })).toEqual({ declared: true, template: null })
    })

    test('a section carrying a template answers with it', () => {
        expect(reportIn({ report: { template: '# {{ run.status }}' } })).toEqual({
            declared: true,
            template: '# {{ run.status }}',
        })
    })

    test('writing one replaces whichever section the document held', () => {
        expect(withReport({ steps: {} }, null)).toEqual({ steps: {}, report: {} })
        expect(withReport({ report: { template: 'old' } }, 'new')).toEqual({ report: { template: 'new' } })
        expect(withoutReport({ steps: {}, report: {} })).toEqual({ steps: {} })
    })

    test('taking one away leaves a document that never had one alone', () => {
        expect(withoutReport({ steps: {} })).toEqual({ steps: {} })
    })
})
