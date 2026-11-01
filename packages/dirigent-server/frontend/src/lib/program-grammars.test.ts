import { compile } from 'monaco-editor/editor/standalone/common/monarch/monarchCompile'
import { MonarchTokenizer } from 'monaco-editor/editor/standalone/common/monarch/monarchLexer'
import { describe, expect, it } from 'vitest'

import { PROGRAM_GRAMMARS } from '@/lib/program-grammars'

/** The services monaco's tokeniser asks for, as far as a grammar with no embedded language needs. */
const languageService = {
    requestBasicLanguageFeatures: () => undefined,
    isRegisteredLanguageId: () => false,
    getLanguageIdByLanguageName: () => null,
}
const configurationService = {
    getValue: () => 20_000,
    onDidChangeConfiguration: () => ({ dispose: () => undefined }),
}

/** Each line of `source` as monaco tokenises it: every run of text and its class, whitespace dropped. */
function tokens(id: string, source: string): [string, string][][] {
    const grammar = PROGRAM_GRAMMARS.find((candidate) => candidate.id === id)
    if (grammar === undefined) throw new Error(`no grammar ${id}`)
    const tokenizer = new MonarchTokenizer(
        languageService,
        {},
        id,
        compile(id, grammar.language),
        configurationService,
    )
    let state = tokenizer.getInitialState()
    return source.split('\n').map((line) => {
        const result = tokenizer.tokenize(line, true, state)
        state = result.endState
        return result.tokens
            .map((token, index): [string, string] => [
                line.slice(token.offset, result.tokens[index + 1]?.offset ?? line.length),
                token.type.replace(`.${id}`, ''),
            ])
            .filter(([text]) => text.trim() !== '')
            .map(([text, kind]): [string, string] => [text.trim(), kind])
    })
}

/** The one line `source` is, tokenised. */
function oneLine(id: string, source: string): [string, string][] {
    return tokens(id, source)[0]
}

describe('the FHIRPath grammar', () => {
    it('reads a path, an operator and a bound variable', () => {
        expect(oneLine('fhirpath', 'valueQuantity.value > %limit')).toEqual([
            ['valueQuantity', 'identifier'],
            ['.', 'delimiter'],
            ['value', 'identifier'],
            ['>', 'operator'],
            ['%limit', 'variable.binding'],
        ])
    })

    it('reads a name followed by a parenthesis as a function, after a dot or not', () => {
        expect(oneLine('fhirpath', "subject.reference.distinct().where(exists() and $this != 'x')")).toEqual([
            ['subject', 'identifier'],
            ['.', 'delimiter'],
            ['reference', 'identifier'],
            ['.', 'delimiter'],
            ['distinct', 'type'],
            ['()', 'delimiter.parenthesis'],
            ['.', 'delimiter'],
            ['where', 'type'],
            ['(', 'delimiter.parenthesis'],
            ['exists', 'type'],
            ['()', 'delimiter.parenthesis'],
            ['and', 'keyword'],
            ['$this', 'variable.binding'],
            ['!=', 'operator'],
            ["'x'", 'string'],
            [')', 'delimiter.parenthesis'],
        ])
    })

    it('keeps a keyword a keyword between operands, and a member a member after a dot', () => {
        expect(oneLine('fhirpath', 'text.div contains name is Patient')).toEqual([
            ['text', 'identifier'],
            ['.', 'delimiter'],
            ['div', 'identifier'],
            ['contains', 'keyword'],
            ['name', 'identifier'],
            ['is', 'keyword'],
            ['Patient', 'identifier'],
        ])
    })

    it('keeps a keyword before a parenthesis a keyword, and a member called as one a function', () => {
        expect(oneLine('fhirpath', "status in ('final') and value.as(Quantity)")).toEqual([
            ['status', 'identifier'],
            ['in', 'keyword'],
            ['(', 'delimiter.parenthesis'],
            ["'final'", 'string'],
            [')', 'delimiter.parenthesis'],
            ['and', 'keyword'],
            ['value', 'identifier'],
            ['.', 'delimiter'],
            ['as', 'type'],
            ['(', 'delimiter.parenthesis'],
            ['Quantity', 'identifier'],
            [')', 'delimiter.parenthesis'],
        ])
    })

    it('reads a backticked name, a quoted or backticked variable, a date and numbers', () => {
        expect(
            oneLine(
                'fhirpath',
                "`given name` = %`vs-codes` or %'us-zip' or @2026-01-01T10:00:00Z or 4.5 > 3",
            ),
        ).toEqual([
            ['`given name`', 'identifier'],
            ['=', 'operator'],
            ['%`vs-codes`', 'variable.binding'],
            ['or', 'keyword'],
            ["%'us-zip'", 'variable.binding'],
            ['or', 'keyword'],
            ['@2026-01-01T10:00:00Z', 'number'],
            ['or', 'keyword'],
            ['4.5', 'number.float'],
            ['>', 'operator'],
            ['3', 'number'],
        ])
    })

    it('keeps an escaped quote inside a string', () => {
        expect(oneLine('fhirpath', "name = 'O\\'Brien'")).toEqual([
            ['name', 'identifier'],
            ['=', 'operator'],
            ["'O\\'Brien'", 'string'],
        ])
    })

    it('reads a line comment, and a block comment across lines', () => {
        expect(tokens('fhirpath', 'value // the reading\n/* one\ntwo */ code')).toEqual([
            [
                ['value', 'identifier'],
                ['// the reading', 'comment'],
            ],
            [['/* one', 'comment']],
            [
                ['two */', 'comment'],
                ['code', 'identifier'],
            ],
        ])
    })
})

describe('the CQL grammar', () => {
    it('reads a declaration: keywords, a quoted name and a string', () => {
        expect(oneLine('cql', `code "Body weight": '29463-7' from "LOINC"`)).toEqual([
            ['code', 'keyword'],
            ['"Body weight"', 'identifier'],
            [':', 'delimiter'],
            ["'29463-7'", 'string'],
            ['from', 'keyword'],
            ['"LOINC"', 'identifier'],
        ])
    })

    it('reads a function, a keyword before a parenthesis, a member and a number', () => {
        expect(
            oneLine('cql', 'define "Heavy": exists (O where AgeInYears() >= 18.5 and O.code is not null)'),
        ).toEqual([
            ['define', 'keyword'],
            ['"Heavy"', 'identifier'],
            [':', 'delimiter'],
            ['exists', 'keyword'],
            ['(', 'delimiter.parenthesis'],
            ['O', 'identifier'],
            ['where', 'keyword'],
            ['AgeInYears', 'type'],
            ['()', 'delimiter.parenthesis'],
            ['>=', 'operator'],
            ['18.5', 'number.float'],
            ['and', 'keyword'],
            ['O', 'identifier'],
            ['.', 'delimiter'],
            ['code', 'identifier'],
            ['is', 'keyword'],
            ['not', 'keyword'],
            ['null', 'keyword'],
            [')', 'delimiter.parenthesis'],
        ])
    })

    it('reads a retrieve, a date literal and a backticked name', () => {
        expect(
            oneLine('cql', '[Observation: `Body weight`] during Interval[@2026-01-01, @2026-12-31]'),
        ).toEqual([
            ['[', 'delimiter.square'],
            ['Observation', 'identifier'],
            [':', 'delimiter'],
            ['`Body weight`', 'identifier'],
            [']', 'delimiter.square'],
            ['during', 'keyword'],
            ['Interval', 'identifier'],
            ['[', 'delimiter.square'],
            ['@2026-01-01', 'number'],
            [',', 'delimiter'],
            ['@2026-12-31', 'number'],
            [']', 'delimiter.square'],
        ])
    })

    it('reads a comment on a line of its own and after code', () => {
        expect(tokens('cql', '// weights\nparameter Limit Decimal default 100.0 /* kg */')).toEqual([
            [['// weights', 'comment']],
            [
                ['parameter', 'keyword'],
                ['Limit', 'identifier'],
                ['Decimal', 'identifier'],
                ['default', 'keyword'],
                ['100.0', 'number.float'],
                ['/* kg */', 'comment'],
            ],
        ])
    })
})

describe('the jq grammar', () => {
    it('reads a path, a binding, a builtin and an interpolated string', () => {
        expect(oneLine('jq', '.rows | map(select(.v > $limit)) | "\\(.name)"')).toEqual([
            ['.rows', 'type'],
            ['|', 'delimiter'],
            ['map', 'type'],
            ['(', 'delimiter.parenthesis'],
            ['select', 'type'],
            ['(', 'delimiter.parenthesis'],
            ['.v', 'type'],
            ['>', 'operator'],
            ['$limit', 'variable.binding'],
            ['))', 'delimiter.parenthesis'],
            ['|', 'delimiter'],
            ['"', 'string'],
            ['\\(', 'delimiter'],
            ['.name', 'type'],
            [')', 'delimiter'],
            ['"', 'string'],
        ])
    })
})
