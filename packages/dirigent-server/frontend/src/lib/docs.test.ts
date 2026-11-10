import { describe, expect, test } from 'vitest'

import { API_DOCS_URL, docsHref, servedByInstance, type DocsTag } from '@/lib/docs'

/** Every tag a screen in this bundle links to, which are `APIRouter(tags=[...])` on the server. */
const TAGS: DocsTag[] = [
    'pipelines',
    'runs',
    'triggers',
    'connections',
    'blocks',
    'users',
    'workers',
    'alerts',
    'audit',
    'system',
]

describe('where a listing points at the API behind it', () => {
    test('is the fragment Swagger UI writes on its own tag headings', () => {
        expect(docsHref('runs')).toBe('/docs#/runs')
    })

    test('is at the root, whatever prefix the versioned API mounted at', () => {
        for (const tag of TAGS) {
            expect(docsHref(tag).startsWith('/docs#/')).toBe(true)
        }
    })

    test('names a different section for every screen that offers the chip', () => {
        expect(new Set(TAGS.map(docsHref)).size).toBe(TAGS.length)
    })
})

describe('which addresses the server draws rather than the router', () => {
    test('is the API documentation, with or without a section', () => {
        expect(servedByInstance(API_DOCS_URL)).toBe(true)
        expect(servedByInstance(docsHref('runs'))).toBe(true)
    })

    test('is never a screen of this app', () => {
        expect(servedByInstance('/runs')).toBe(false)
        expect(servedByInstance('/docsets')).toBe(false)
    })
})
