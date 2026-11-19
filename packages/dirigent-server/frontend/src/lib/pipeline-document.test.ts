import { beforeEach, describe, expect, test } from 'vitest'

import type { JsonMap } from '@/lib/api'
import { LABELS } from '@/lib/labels'
import {
    applyVariant,
    blockOf,
    stepRuns,
    changeDocument,
    configOf,
    configSummary,
    dependsOn,
    documentApplied,
    documentStore,
    documentUnsaved,
    edgesIn,
    editsIn,
    editsLabel,
    fanOutOf,
    forgetDocument,
    fromYaml,
    liftedDocument,
    loadDocument,
    NEW_CODE,
    NEW_DOCUMENT,
    newDocument,
    parkDocument,
    reportIn,
    resumeDocument,
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

    test('an edge drawn and taken back again is no edit, though the stored step said depends_on: []', () => {
        const held = document()
        const stored: JsonMap = {
            ...held,
            steps: {
                ...(held.steps as JsonMap),
                parse: { ...(held.steps as Record<string, JsonMap>).parse, depends_on: [] },
            },
        }
        const drawn = withDependsOn(withDependsOn(stored, 'parse', ['report']), 'parse', [])
        expect(editsIn(stored, drawn).count).toBe(0)
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
        expect(toYaml(stored).split('\n').slice(0, 3)).toEqual([
            'format: dirigent/v1',
            'kind: pipeline',
            'code: review-dag',
        ])
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

    // Each expectation is what `dirigent_core.documents.safe_load` reads from the same text.
    test('reads every scalar the way dg apply reads it', () => {
        const text = [
            'defaults: &defaults',
            '  retries: 3',
            'config:',
            '  <<: *defaults',
            '  country: NO',
            '  enabled: yes',
            '  flag: on',
            '  letter: y',
            '  at: 12:30',
            '  late: 12:60',
            '  mode: 0755',
            '  nine: 09',
            '  octal12: 0o17',
            '  big: 1_000',
            '  sci: 1e3',
            '  signed: 1.5e+3',
            '  unsigned: 1.5e3',
            '  half: .5',
            '  negative_half: -.5',
            '  hex: 0x1F',
            '  day: 2026-01-01',
        ].join('\n')
        const read = fromYaml(text)
        expect(read.ok && read.document.config).toEqual({
            retries: 3,
            country: false,
            enabled: true,
            flag: true,
            letter: 'y',
            at: 750,
            late: '12:60',
            mode: 493,
            nine: '09',
            octal12: '0o17',
            big: 1000,
            sci: '1e3',
            signed: 1500,
            unsigned: '1.5e3',
            half: 0.5,
            negative_half: '-.5',
            hex: 31,
            day: '2026-01-01',
        })
    })

    test('writes a string dg apply would read as something else in quotes, and a number as one', () => {
        const config = {
            country: 'NO',
            enabled: 'yes',
            flag: 'on',
            at: '12:30',
            big: '1_000',
            octal: '0755',
            huge: 1e21,
            tiny: 1e-7,
            ratio: 1.5,
            count: 7,
            letter: 'y',
            day: '2026-01-01',
            merge: '<<',
            value: '=',
        }
        const text = toYaml({ code: 'quoted', steps: {}, config })
        for (const said of [
            '"NO"',
            '"yes"',
            '"on"',
            '"12:30"',
            '"1_000"',
            '"0755"',
            '1.0e+21',
            '1.0e-7',
            '"<<"',
            '"="',
        ]) {
            expect(text).toContain(said)
        }
        const read = fromYaml(text)
        expect(read.ok && read.document.config).toEqual(config)
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

    test('refuses a number JSON cannot carry, by the key that holds it, rather than sending it as null', () => {
        expect(fromYaml('code: big\nsteps: {}\nconfig:\n  limit: .inf')).toEqual({
            ok: false,
            message: 'config.limit: an infinity or NaN cannot be sent; write a finite number or a string',
        })
        const deep = fromYaml(
            'code: deep\nsteps:\n  pick:\n    config:\n      bounds: [0, -.inf]\n      ratio: .nan',
        )
        expect(deep.ok === false && deep.message.startsWith('steps.pick.config.bounds[1]:')).toBe(true)
        expect(fromYaml("code: fine\nsteps: {}\nconfig:\n  limit: '.inf'")).toEqual({
            ok: true,
            document: { code: 'fine', steps: {}, config: { limit: '.inf' } },
        })
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

    test('keeps an infinity out of the document an apply would send', () => {
        loadDocument('convert-one', document())
        const typed = toYaml(document()).replace('steps:', 'config:\n  limit: .inf\nsteps:')
        writeSource(typed)
        const state = documentStore.get()
        expect(state.parseError).toMatch(/^config\.limit:/)
        expect(state.draft).toBe(typed)
        expect(state.local).toEqual(document())
    })

    test('shows text that was typed as it was typed, comments and all', () => {
        loadDocument('convert-one', document())
        const typed = `# what this pipeline is for\n${toYaml(document())}`
        writeSource(typed)
        const state = documentStore.get()
        expect(state.source).toBe(typed)
        expect(stepNames(state.local)).toEqual(['parse', 'report'])
    })

    test('a structural edit drops the text, because no renderer can produce it', () => {
        loadDocument('convert-one', document())
        writeSource(`# what this pipeline is for\n${toYaml(document())}`)
        changeDocument((current) => withStepConfig(current, 'parse', { from: 'csv' }))
        expect(documentStore.get().source).toBeNull()
    })

    test('text that does not parse leaves the text the pane holds alone', () => {
        loadDocument('convert-one', document())
        const typed = `# what this pipeline is for\n${toYaml(document())}`
        writeSource(typed)
        writeSource('steps:\n  parse: [')
        const state = documentStore.get()
        expect(state.source).toBe(typed)
        expect(state.draft).toBe('steps:\n  parse: [')
        expect(state.parseError).not.toBeNull()
    })

    test('reverting goes back to rendering the document', () => {
        loadDocument('convert-one', document())
        writeSource(`# what this pipeline is for\n${toYaml(document())}`)
        revertDocument()
        expect(documentStore.get().source).toBeNull()
    })

    test('refuses an edit from another tab while the source does not parse', () => {
        loadDocument('convert-one', document())
        writeSource('steps:\n  parse: [')
        expect(changeDocument((current) => withStepConfig(current, 'parse', { from: 'csv' }))).toBe(false)
        expect(configOf(documentStore.get().local, 'parse')).toEqual({
            from: 'json',
            to: 'yaml',
            input: '{}',
        })
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
            source: null,
            draft: null,
            parseError: null,
        })
    })
})

describe('whether leaving would lose anything', () => {
    test('a document as the instance holds it loses nothing, and one edit is something', () => {
        loadDocument('convert-one', document())
        expect(documentUnsaved(documentStore.get())).toBe(false)
        changeDocument((current) => withStepConfig(current, 'parse', { from: 'csv' }))
        expect(documentUnsaved(documentStore.get())).toBe(true)
    })

    test('text in the source pane that does not parse is something, though the document is unchanged', () => {
        loadDocument('convert-one', document())
        writeSource('steps:\n  parse: [')
        expect(documentUnsaved(documentStore.get())).toBe(true)
    })

    test('a new document is something once it differs from the skeleton it opened on', () => {
        startDocument()
        expect(documentUnsaved(documentStore.get())).toBe(false)
        changeDocument((current) => ({ ...current, code: 'mine' }))
        expect(documentUnsaved(documentStore.get())).toBe(true)
    })
})

describe('a document set aside while its account signs in again', () => {
    test('is taken up again for the same account and pipeline, edits and unparsed text with it', () => {
        loadDocument('convert-one', document())
        changeDocument((current) => withStepConfig(current, 'parse', { from: 'csv' }))
        writeSource('steps:\n  parse: [')
        const before = documentStore.get()
        parkDocument('admin')
        forgetDocument()

        expect(resumeDocument('convert-one', 'admin', document())).toBe(true)
        expect(documentStore.get()).toEqual(before)
    })

    test('is not taken up by another account, another pipeline, or over a version that moved', () => {
        for (const [code, username, applied] of [
            ['convert-one', 'someone-else', document()],
            ['another', 'admin', document()],
            ['convert-one', 'admin', { ...document(), name: 'Moved on' }],
        ] as const) {
            loadDocument('convert-one', document())
            changeDocument((current) => withStepConfig(current, 'parse', { from: 'csv' }))
            parkDocument('admin')
            forgetDocument()
            expect(resumeDocument(code, username, applied)).toBe(false)
            expect(documentStore.get().local).toBeNull()
        }
    })

    test('is taken up once only', () => {
        loadDocument('convert-one', document())
        parkDocument('admin')
        expect(resumeDocument('convert-one', 'admin', document())).toBe(true)
        expect(resumeDocument('convert-one', 'admin', document())).toBe(false)
    })
})

describe('the version an apply wrote', () => {
    test('becomes the document when nothing was edited while it was answering', () => {
        loadDocument('convert-one', document())
        changeDocument((current) => withStepConfig(current, 'parse', { from: 'csv' }))
        const sent = documentStore.get().local as JsonMap
        const written = { ...sent, name: 'As stored' }
        documentApplied('convert-one', sent, written)
        expect(documentStore.get().local).toEqual(written)
        expect(documentUnsaved(documentStore.get())).toBe(false)
    })

    test('leaves an edit made while it was answering in place, measured against what was written', () => {
        loadDocument('convert-one', document())
        changeDocument((current) => withStepConfig(current, 'parse', { from: 'csv' }))
        const sent = documentStore.get().local as JsonMap
        changeDocument((current) => withStepConfig(current, 'parse', { from: 'tsv' }))
        const typed = documentStore.get().local
        documentApplied('convert-one', sent, sent)
        expect(documentStore.get().local).toBe(typed)
        expect(documentStore.get().applied).toEqual(sent)
        expect(editsIn(documentStore.get().applied, documentStore.get().local).steps).toEqual(['parse'])
    })
})

describe('lifting what a document carries', () => {
    beforeEach(forgetDocument)

    /** A starter as a shelf holds one: comments, a carried schema, and a carried connection. */
    const CARRYING = [
        '# A night over eight regions.',
        'format: dirigent/v1',
        'kind: pipeline',
        'code: nightly-regional-load',
        '',
        'requires:',
        '  blocks:',
        '    - validate.schema',
        '',
        '# Carried, so a --local run has the shapes without an instance holding them.',
        'schemas:',
        '  nightly-catalogue:',
        '    type: object',
        '',
        'connections:',
        '  ops-receiver:',
        '    kind: http',
        '',
        'steps:',
        '  check:',
        '    block: validate.schema',
        '    # The gate every region is read through.',
        '    config:',
        '      schema: nightly-catalogue',
        '',
    ].join('\n')

    /**
     * THIS IS WHAT THE REFUSED APPLY SENDS. Both sections come out and their codes are named
     * under `requires:`, which is exactly what `dg pipeline new` writes into a project.
     */
    test('takes both sections out and names their codes under requires', () => {
        startDocument(CARRYING)
        const lifted = liftedDocument()
        expect(lifted?.schemas).toBeUndefined()
        expect(lifted?.connections).toBeUndefined()
        expect(lifted?.requires).toEqual({
            blocks: ['validate.schema'],
            schemas: ['nightly-catalogue'],
            connections: ['ops-receiver'],
        })
    })

    test('writes nothing back, so a lift nobody applied never reaches the pane', () => {
        startDocument(CARRYING)
        liftedDocument()
        const state = documentStore.get()
        expect(state.source).toBe(CARRYING)
        expect(state.local?.schemas).toBeDefined()
    })

    test('lifts a document that has no text any more, which is one a form has edited', () => {
        startDocument(CARRYING)
        changeDocument((current) => withStepName(current, 'check', 'The gate'))
        expect(documentStore.get().source).toBeNull()
        const lifted = liftedDocument()
        expect(lifted?.schemas).toBeUndefined()
        expect(lifted?.requires).toEqual({
            blocks: ['validate.schema'],
            schemas: ['nightly-catalogue'],
            connections: ['ops-receiver'],
        })
    })

    test('leaves a document that carries nothing exactly as it stands', () => {
        loadDocument('convert-one', document())
        expect(liftedDocument()).toEqual(document())
    })

    test('answers with nothing while the source pane holds text that is not a document', () => {
        startDocument(CARRYING)
        writeSource('steps:\n  parse: [')
        expect(liftedDocument()).toBeNull()
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

    test('opens on the text it was handed, comments and all', () => {
        const starter = [
            '# Render a page of markdown and put it in a file.',
            '#',
            '# TO MAKE IT YOURS: change the template.',
            'format: dirigent/v1',
            'kind: pipeline',
            'code: report-to-file',
            'steps:',
            '  page:',
            '    block: report.render',
            '',
        ].join('\n')
        startDocument(starter)
        const state = documentStore.get()
        expect(state.source).toBe(starter)
        expect(state.local?.code).toBe('report-to-file')
        expect(stepNames(state.local)).toEqual(['page'])
    })

    test('opens on no text at all when nothing was handed in', () => {
        startDocument()
        expect(documentStore.get().source).toBeNull()
    })

    test('keeps text that does not parse as the draft, with no document text to show', () => {
        startDocument('steps:\n  parse: [')
        const state = documentStore.get()
        expect(state.source).toBeNull()
        expect(state.draft).toBe('steps:\n  parse: [')
        expect(state.parseError).not.toBeNull()
    })

    test('is edited like any other: the source pane writes it and the graph reads it', () => {
        startDocument()
        writeSource(
            'format: dirigent/v1\nkind: pipeline\ncode: mine\nsteps:\n  one:\n    block: transform.jq\n',
        )
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

describe('what a step says where its block would be', () => {
    const shapes: JsonMap = {
        steps: {
            ask: { source: { kind: 'endpoint' } },
            work: { block: 'transform.jq' },
            answer: { reply: { status: 200 } },
            bare: {},
        },
    }

    test('is its block, its source kind, or reply, and no block for a step that is none of them', () => {
        expect(stepRuns(shapes, 'work')).toBe('transform.jq')
        expect(stepRuns(shapes, 'ask')).toBe('endpoint')
        expect(stepRuns(shapes, 'answer')).toBe(LABELS.editor.reply)
        expect(stepRuns(shapes, 'bare')).toBe(LABELS.editor.no_block)
    })
})
