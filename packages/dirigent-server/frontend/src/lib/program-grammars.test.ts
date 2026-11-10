import { StringStream, type StreamParser } from '@codemirror/language'
import { describe, expect, it } from 'vitest'

import { cqlParser, fhirpathParser, type ProgramState } from '@/lib/program-grammars'

/** Each line of `source` as the parser reads it: every token and its tag, whitespace dropped. */
function tokens(parser: StreamParser<ProgramState>, source: string): [string, string | null][][] {
    const state = parser.startState!(2)
    return source.split('\n').map((line) => {
        const read: [string, string | null][] = []
        const stream = new StringStream(line, 4, 2)
        while (!stream.eol()) {
            const tag = parser.token(stream, state)
            const text = stream.current()
            if (text.trim() !== '') read.push([text.trim(), tag])
            stream.start = stream.pos
        }
        return read
    })
}

/** The one line `source` is, read. */
function oneLine(parser: StreamParser<ProgramState>, source: string): [string, string | null][] {
    return tokens(parser, source)[0]
}

describe('the FHIRPath grammar', () => {
    it('reads a path, an operator and a bound variable', () => {
        expect(oneLine(fhirpathParser, 'valueQuantity.value > %limit')).toEqual([
            ['valueQuantity', 'variableName'],
            ['.', 'punctuation'],
            ['value', 'propertyName'],
            ['>', 'operator'],
            ['%limit', 'variableName.special'],
        ])
    })

    it('reads a name followed by a parenthesis as a function, after a dot or not', () => {
        expect(
            oneLine(fhirpathParser, "subject.reference.distinct().where(exists() and $this != 'x')"),
        ).toEqual([
            ['subject', 'variableName'],
            ['.', 'punctuation'],
            ['reference', 'propertyName'],
            ['.', 'punctuation'],
            ['distinct', 'variableName.function'],
            ['(', 'bracket'],
            [')', 'bracket'],
            ['.', 'punctuation'],
            ['where', 'variableName.function'],
            ['(', 'bracket'],
            ['exists', 'variableName.function'],
            ['(', 'bracket'],
            [')', 'bracket'],
            ['and', 'keyword'],
            ['$this', 'variableName.special'],
            ['!=', 'operator'],
            ["'x'", 'string'],
            [')', 'bracket'],
        ])
    })

    it('keeps a keyword a keyword between operands, and a member a member after a dot', () => {
        expect(oneLine(fhirpathParser, 'text.div contains name is Patient')).toEqual([
            ['text', 'variableName'],
            ['.', 'punctuation'],
            ['div', 'propertyName'],
            ['contains', 'keyword'],
            ['name', 'variableName'],
            ['is', 'keyword'],
            ['Patient', 'variableName'],
        ])
    })

    it('keeps a keyword before a parenthesis a keyword, and a member called as one a function', () => {
        expect(oneLine(fhirpathParser, "status in ('final') and value.as(Quantity)")).toEqual([
            ['status', 'variableName'],
            ['in', 'keyword'],
            ['(', 'bracket'],
            ["'final'", 'string'],
            [')', 'bracket'],
            ['and', 'keyword'],
            ['value', 'variableName'],
            ['.', 'punctuation'],
            ['as', 'variableName.function'],
            ['(', 'bracket'],
            ['Quantity', 'variableName'],
            [')', 'bracket'],
        ])
    })

    it('reads a backticked name, a quoted or backticked variable, a date, a literal and numbers', () => {
        expect(
            oneLine(
                fhirpathParser,
                "`given name` = %`vs-codes` or %'us-zip' or @2026-01-01T10:00:00Z or true or 4.5 > 3",
            ),
        ).toEqual([
            ['`given name`', 'variableName'],
            ['=', 'operator'],
            ['%`vs-codes`', 'variableName.special'],
            ['or', 'keyword'],
            ["%'us-zip'", 'variableName.special'],
            ['or', 'keyword'],
            ['@2026-01-01T10:00:00Z', 'number'],
            ['or', 'keyword'],
            ['true', 'bool'],
            ['or', 'keyword'],
            ['4.5', 'number'],
            ['>', 'operator'],
            ['3', 'number'],
        ])
    })

    it('keeps an escaped quote inside a string, and marks a string left open', () => {
        expect(oneLine(fhirpathParser, "name = 'O\\'Brien'")).toEqual([
            ['name', 'variableName'],
            ['=', 'operator'],
            ["'O\\'Brien'", 'string'],
        ])
        expect(oneLine(fhirpathParser, "name = 'open")).toEqual([
            ['name', 'variableName'],
            ['=', 'operator'],
            ["'open", 'invalid'],
        ])
    })

    it('reads a line comment, and a block comment across lines', () => {
        expect(tokens(fhirpathParser, 'value // the reading\n/* one\ntwo */ code')).toEqual([
            [
                ['value', 'variableName'],
                ['// the reading', 'comment'],
            ],
            [['/* one', 'comment']],
            [
                ['two */', 'comment'],
                ['code', 'variableName'],
            ],
        ])
    })
})

describe('the CQL grammar', () => {
    it('reads a declaration: keywords, a quoted name and a string', () => {
        expect(oneLine(cqlParser, `code "Body weight": '29463-7' from "LOINC"`)).toEqual([
            ['code', 'keyword'],
            ['"Body weight"', 'variableName'],
            [':', 'punctuation'],
            ["'29463-7'", 'string'],
            ['from', 'keyword'],
            ['"LOINC"', 'variableName'],
        ])
    })

    it('reads a function, a keyword before a parenthesis, a member and a number', () => {
        expect(
            oneLine(
                cqlParser,
                'define "Heavy": exists (O where AgeInYears() >= 18.5 and O.code is not null)',
            ),
        ).toEqual([
            ['define', 'keyword'],
            ['"Heavy"', 'variableName'],
            [':', 'punctuation'],
            ['exists', 'keyword'],
            ['(', 'bracket'],
            ['O', 'variableName'],
            ['where', 'keyword'],
            ['AgeInYears', 'variableName.function'],
            ['(', 'bracket'],
            [')', 'bracket'],
            ['>=', 'operator'],
            ['18.5', 'number'],
            ['and', 'keyword'],
            ['O', 'variableName'],
            ['.', 'punctuation'],
            ['code', 'propertyName'],
            ['is', 'keyword'],
            ['not', 'keyword'],
            ['null', 'null'],
            [')', 'bracket'],
        ])
    })

    it('reads a retrieve, a date literal and a backticked name', () => {
        expect(
            oneLine(cqlParser, '[Observation: `Body weight`] during Interval[@2026-01-01, @2026-12-31]'),
        ).toEqual([
            ['[', 'bracket'],
            ['Observation', 'variableName'],
            [':', 'punctuation'],
            ['`Body weight`', 'variableName'],
            [']', 'bracket'],
            ['during', 'keyword'],
            ['Interval', 'variableName'],
            ['[', 'bracket'],
            ['@2026-01-01', 'number'],
            [',', 'punctuation'],
            ['@2026-12-31', 'number'],
            [']', 'bracket'],
        ])
    })

    it('reads a comment on a line of its own and after code, and a long integer', () => {
        expect(tokens(cqlParser, '// weights\nparameter Limit Decimal default 100L /* kg */')).toEqual([
            [['// weights', 'comment']],
            [
                ['parameter', 'keyword'],
                ['Limit', 'variableName'],
                ['Decimal', 'variableName'],
                ['default', 'keyword'],
                ['100L', 'number'],
                ['/* kg */', 'comment'],
            ],
        ])
    })
})
