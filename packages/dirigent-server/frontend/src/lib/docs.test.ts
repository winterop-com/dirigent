import { describe, expect, test } from 'vitest'

import { docsHref, type DocsTag } from '@/lib/docs'

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
