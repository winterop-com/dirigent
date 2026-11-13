import { StringStream, type StreamParser } from '@codemirror/language'
import { describe, expect, it } from 'vitest'

import { pluginLanguage, registerPlugins } from '@winterop-com/sokkel-ui/lib/plugins'
import { fhir } from '@winterop-com/sokkel-ui-fhir/plugin'

import { languageOf } from '@/components/pipeline/CodeEditor'

registerPlugins([fhir])

/** The media types dirigent-common names for a FHIRPath expression and a CQL library. */
const FHIRPATH_MEDIA_TYPE = 'application/fhirpath'
const CQL_MEDIA_TYPE = 'text/cql'

/** The first line of `source` as the language of `mediaType` reads it: each token and its tag. */
function tokens(mediaType: string, source: string): [string, string | null][] {
    const name = languageOf(mediaType)
    if (typeof name !== 'string') throw new Error(`${mediaType} read as a language object`)
    const parser = pluginLanguage(name)?.language as StreamParser<unknown> | undefined
    if (parser === undefined) throw new Error(`${mediaType} reads as ${name}, which no plugin installed`)
    const state = parser.startState!(2)
    const read: [string, string | null][] = []
    const stream = new StringStream(source.split('\n')[0], 4, 2)
    while (!stream.eol()) {
        const tag = parser.token(stream, state)
        const text = stream.current().trim()
        if (text !== '') read.push([text, tag])
        stream.start = stream.pos
    }
    return read
}

describe('a program field read by its media type', () => {
    it('reads FHIRPath and CQL by the media types the fhir pack publishes', () => {
        expect(languageOf(FHIRPATH_MEDIA_TYPE)).toBe('fhirpath')
        expect(languageOf(CQL_MEDIA_TYPE)).toBe('cql')
    })

    it('highlights a FHIRPath keyword and a bound variable', () => {
        expect(tokens(FHIRPATH_MEDIA_TYPE, 'value > %limit and active')).toEqual([
            ['value', 'variableName'],
            ['>', 'operator'],
            ['%limit', 'variableName.special'],
            ['and', 'keyword'],
            ['active', 'variableName'],
        ])
    })

    it('highlights a CQL definition', () => {
        expect(tokens(CQL_MEDIA_TYPE, 'define "In Range": true')).toEqual([
            ['define', 'keyword'],
            ['"In Range"', 'variableName'],
            [':', 'punctuation'],
            ['true', 'bool'],
        ])
    })

    it('reads a buffer with no media type as YAML', () => {
        expect(languageOf(null)).toBe('yaml')
    })
})
