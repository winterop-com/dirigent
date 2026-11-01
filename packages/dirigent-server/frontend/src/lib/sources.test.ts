import { describe, expect, test } from 'vitest'

import { LABELS } from '@/lib/labels'
import {
    authLine,
    curlLine,
    declaredMethods,
    endpointUrl,
    handEntryOf,
    listeningLine,
    sampleBody,
} from '@/lib/sources'

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

describe('where a received source is called', () => {
    test('is the origin and the path, with no slash doubled', () => {
        expect(endpointUrl('http://127.0.0.1:3471/', endpoint)).toBe(
            'http://127.0.0.1:3471/endpoints/signups',
        )
        expect(endpointUrl('http://127.0.0.1:3471', polled)).toBeNull()
    })

    test('a curl line carries the token and the sample body, quoted for the shell', () => {
        const line = curlLine({
            url: 'http://h/endpoints/echo',
            method: 'post',
            token: 'tok_1',
            body: { said: "it's" },
        })
        expect(line).toBe(
            `curl -X POST 'http://h/endpoints/echo' -H 'Authorization: Bearer tok_1' -H 'Content-Type: application/json' -d '{"said":"it'\\''s"}'`,
        )
    })

    test('a curl line sends no body with a method that carries none', () => {
        const line = curlLine({ url: 'http://h/e', method: 'GET', token: 't', body: { a: 1 } })
        expect(line).toBe(`curl -X GET 'http://h/e' -H 'Authorization: Bearer t'`)
    })

    test('a source with no sample sends an empty object', () => {
        expect(curlLine({ url: 'u', method: 'POST', token: 't', body: undefined })).toContain(`-d '{}'`)
    })
})

describe('how a caller authenticates', () => {
    test('names a bearer token by its prefix and a signature by its header', () => {
        const base = {
            auth: 'token',
            token_prefix: 'dgs_ab',
            secret_fingerprint: null,
            signature_header: null,
        }
        expect(authLine(base)).toBe(LABELS.triggers.source.token('dgs_ab'))
        expect(
            authLine({ ...base, auth: 'hmac', secret_fingerprint: 'f00', signature_header: 'X-Signature' }),
        ).toBe(LABELS.triggers.source.signed('X-Signature', 'f00'))
        expect(authLine({ ...base, auth: 'public' })).toBe(LABELS.triggers.source.public)
    })
})

describe('what a hand run enters', () => {
    const echo = {
        steps: {
            ask: {
                source: { kind: 'endpoint', path: '/echo', methods: ['PUT'] },
                sample: { body: { said: 'hi' } },
            },
            answer: { depends_on: ['ask'], reply: { status: 200 } },
        },
    }

    test('is the one source, said with its sample and whether a reply follows', () => {
        expect(handEntryOf(echo)).toEqual({ step: 'ask', sampled: true, replies: true })
        expect(sampleBody(echo, 'ask')).toEqual({ said: 'hi' })
        expect(declaredMethods(echo, 'ask')).toEqual(['PUT'])
    })

    test('says an empty input where there is no sample, and no reply where there is none', () => {
        const bare = {
            steps: { ask: { source: { kind: 'endpoint', path: '/x' } }, work: { block: 'test.echo' } },
        }
        expect(handEntryOf(bare)).toEqual({ step: 'ask', sampled: false, replies: false })
        expect(sampleBody(bare, 'ask')).toBeUndefined()
        expect(declaredMethods(bare, 'ask')).toEqual(['POST'])
    })

    test('is nothing for a document with no source or with several', () => {
        expect(handEntryOf(null)).toBeNull()
        expect(handEntryOf({ steps: { one: { block: 'test.echo' } } })).toBeNull()
        const two = { steps: { a: { source: { kind: 'endpoint' } }, b: { source: { kind: 'endpoint' } } } }
        expect(handEntryOf(two)).toBeNull()
    })
})
