import { describe, expect, it } from 'vitest'

import {
    EVERY_EXAMPLE,
    anythingFiltered,
    carriesNote,
    examplesPerBlock,
    filtersFromQuery,
    missingCount,
    narrowExamples,
    pluginsOffered,
    queryOf,
    requirementsOf,
    requirementsSummary,
    shelveStarters,
    shelvesOffered,
    starterMatches,
    tagsOffered,
    type ExampleOut,
    type Holdings,
    type Requirements,
} from '@/lib/examples'

const NOTHING: Requirements = {
    blocks: [],
    connections: [],
    pipelines: [],
    storage: [],
    schemas: [],
    workers: [],
}

function example(code: string, over: Partial<ExampleOut> = {}): ExampleOut {
    return {
        code,
        name: null,
        description: null,
        tags: [],
        requires: NOTHING,
        plugin: 'examples',
        shelf: 'recipes',
        starter: false,
        carries: [],
        ...over,
    }
}

const CORPUS: ExampleOut[] = [
    example('http-fetch-validate-post', {
        name: 'Fetch, validate, post',
        description: 'A real flow on a real source.',
        tags: ['recipes', 'http', 'starter'],
        starter: true,
        requires: { ...NOTHING, blocks: ['http.request', 'validate.schema'], connections: ['warehouse'] },
    }),
    example('hello-world', { shelf: '', tags: ['demo'] }),
    example('kafka-consume-then-transform', {
        tags: ['queues', 'kafka', 'starter'],
        shelf: 'queues',
        starter: true,
        requires: { ...NOTHING, blocks: ['kafka.consume'], connections: ['orders-topic'] },
    }),
    example('carried-connections', {
        shelf: 'demo',
        carries: ['connections'],
        requires: { ...NOTHING, blocks: ['http.request'] },
    }),
]

describe('narrowExamples', () => {
    it('answers the whole corpus when nothing is being narrowed', () => {
        expect(narrowExamples(CORPUS, EVERY_EXAMPLE)).toHaveLength(CORPUS.length)
        expect(anythingFiltered(EVERY_EXAMPLE)).toBe(false)
    })

    it('narrows to the starters', () => {
        const shown = narrowExamples(CORPUS, { ...EVERY_EXAMPLE, starters: true })
        expect(shown.map((row) => row.code)).toEqual([
            'http-fetch-validate-post',
            'kafka-consume-then-transform',
        ])
    })

    it('takes every tag, so a second one narrows rather than widens', () => {
        expect(narrowExamples(CORPUS, { ...EVERY_EXAMPLE, tags: ['starter'] })).toHaveLength(2)
        expect(narrowExamples(CORPUS, { ...EVERY_EXAMPLE, tags: ['starter', 'kafka'] })).toHaveLength(1)
        expect(narrowExamples(CORPUS, { ...EVERY_EXAMPLE, tags: ['starter', 'nothing'] })).toHaveLength(0)
    })

    it('narrows by shelf, by plugin and by the block a document requires', () => {
        expect(narrowExamples(CORPUS, { ...EVERY_EXAMPLE, shelf: 'queues' })).toHaveLength(1)
        expect(narrowExamples(CORPUS, { ...EVERY_EXAMPLE, plugin: 'examples' })).toHaveLength(4)
        expect(
            narrowExamples(CORPUS, { ...EVERY_EXAMPLE, block: 'http.request' }).map((row) => row.code),
        ).toEqual(['http-fetch-validate-post', 'carried-connections'])
    })

    it('searches the code, the name, the description and the tags', () => {
        expect(narrowExamples(CORPUS, { ...EVERY_EXAMPLE, needle: 'kafka' })).toHaveLength(1)
        expect(narrowExamples(CORPUS, { ...EVERY_EXAMPLE, needle: 'real source' })).toHaveLength(1)
        expect(narrowExamples(CORPUS, { ...EVERY_EXAMPLE, needle: 'demo' })).toHaveLength(1)
    })
})

describe('the address', () => {
    it('is read back as the filters it was written from', () => {
        const filters = {
            needle: 'usgs',
            tags: ['http', 'starter'],
            shelf: 'recipes',
            plugin: 'examples',
            starters: true,
            block: 'http.request',
        }
        expect(filtersFromQuery(queryOf(filters))).toEqual(filters)
    })

    it('writes nothing for a filter nobody set', () => {
        expect(queryOf(EVERY_EXAMPLE).toString()).toBe('')
    })

    it('reads a link that carries only a block', () => {
        expect(filtersFromQuery(new URLSearchParams('block=http.request'))).toEqual({
            ...EVERY_EXAMPLE,
            block: 'http.request',
        })
    })
})

describe('requirements', () => {
    const holdings: Holdings = { blocks: ['http.request'], connections: [], schemas: null }

    it('checks what the instance can answer for and states the rest', () => {
        const items = requirementsOf(
            {
                ...NOTHING,
                blocks: ['http.request', 'kafka.consume'],
                connections: ['warehouse'],
                schemas: ['reading'],
                pipelines: ['upstream'],
            },
            holdings,
        )
        expect(items.find((one) => one.name === 'http.request')?.met).toBe(true)
        expect(items.find((one) => one.name === 'kafka.consume')?.met).toBe(false)
        expect(items.find((one) => one.name === 'warehouse')?.met).toBe(false)
        // The schemas listing was refused, so nothing is claimed of what it would have said.
        expect(items.find((one) => one.name === 'reading')?.met).toBeNull()
        // A required pipeline is nobody's to check here.
        expect(items.find((one) => one.name === 'upstream')?.met).toBeNull()
        expect(missingCount(items)).toBe(2)
    })

    it('counts what a document needs, and says how much of it is not here', () => {
        expect(requirementsSummary([])).toBeNull()
        const met = requirementsOf({ ...NOTHING, blocks: ['http.request'] }, holdings)
        expect(requirementsSummary(met)).toBe('1 block')
        const unmet = requirementsOf(
            { ...NOTHING, connections: ['a', 'b'], schemas: ['c'] },
            {
                ...holdings,
                schemas: [],
            },
        )
        expect(requirementsSummary(unmet)).toBe('2 connections, 1 schema, 3 missing')
    })
})

describe('the corpus as a whole', () => {
    it('offers the tags, the shelves and the plugins it wears', () => {
        expect(tagsOffered(CORPUS)).toEqual(['demo', 'http', 'kafka', 'queues', 'recipes', 'starter'])
        expect(shelvesOffered(CORPUS)).toEqual(['demo', 'queues', 'recipes'])
        expect(pluginsOffered(CORPUS)).toEqual(['examples'])
    })

    it('counts the documents that require each block', () => {
        const counted = examplesPerBlock(CORPUS)
        expect(counted.get('http.request')).toBe(2)
        expect(counted.get('kafka.consume')).toBe(1)
        expect(counted.get('shell.run')).toBeUndefined()
    })

    it('says what a document carries that an instance refuses', () => {
        expect(carriesNote(CORPUS[3] as ExampleOut)).toBe('carries connections')
        expect(carriesNote(CORPUS[1] as ExampleOut)).toBeNull()
    })

    it('shelves the starters by plugin and then by directory', () => {
        const shelves = shelveStarters(CORPUS)
        expect(shelves.map((shelf) => shelf.label)).toEqual(['examples ▸ queues', 'examples ▸ recipes'])
        expect(shelves[1]?.rows.map((row) => row.code)).toEqual(['http-fetch-validate-post'])
    })

    it('narrows the picker by every term that was typed', () => {
        const row = CORPUS[0] as ExampleOut
        expect(starterMatches(row, 'fetch post')).toBe(true)
        expect(starterMatches(row, 'fetch kafka')).toBe(false)
        expect(starterMatches(row, '')).toBe(true)
    })
})
