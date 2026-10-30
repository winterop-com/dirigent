import { describe, expect, test } from 'vitest'

import { listeningLine } from '@/lib/sources'

const endpoint = { code: 'signup', methods: ['POST'], url_path: '/endpoints/signups', summary: null }
const polled = { code: 'arrivals', methods: [], url_path: null, summary: 'prefix incoming/' }

describe('what a source says on a graph', () => {
    test('is the route a received source answers', () => {
        expect(listeningLine([endpoint], 'signup', 'endpoint')).toBe('POST /endpoints/signups')
    })

    test('is what a polled kind says of itself', () => {
        expect(listeningLine([polled], 'arrivals', 'storage')).toBe('prefix incoming/')
    })

    test('is the kind where the instance holds nothing for that step yet', () => {
        expect(listeningLine([], 'signup', 'endpoint')).toBe('endpoint')
        expect(listeningLine([polled], 'signup', 'endpoint')).toBe('endpoint')
    })
})
