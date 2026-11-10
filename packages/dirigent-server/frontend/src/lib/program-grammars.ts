import type { StreamParser, StringStream } from '@codemirror/language'

/**
 * FHIRPath and CQL as CodeMirror stream parsers, the two program languages the code editor
 * does not carry.
 *
 * Each token is named by a highlight tag the editor colors: `keyword`, `bool`, `null`, `number`,
 * `string`, `comment`, `operator`, `bracket`, `punctuation`, `variableName.function` for a
 * function, `propertyName` for a member after a dot, `variableName.special` for a name bound
 * outside the program, and `variableName` for every other name.
 */

/** Where a line starts: inside a `/* ... *\/` comment carried over from the line before, or not. */
export interface ProgramState {
    comment: boolean
    /** The last token was a `.`, so the next name is a member even when spelled like a keyword. */
    member: boolean
}

/** A date, a time or a date-time written as a literal, `@2026-01-01T10:00:00Z` or `@T10:00`. */
const TEMPORAL =
    /^@(?:T\d{2}(?::\d{2}(?::\d{2}(?:\.\d+)?)?)?|\d{4}(?:-\d{2}(?:-\d{2})?)?(?:T(?:\d{2}(?::\d{2}(?::\d{2}(?:\.\d+)?)?)?)?(?:Z|[+-]\d{2}:\d{2})?)?)/

const NAME = /^[A-Za-z_]\w*/

/** The rest of a block comment, up to and including its close when it is on this line. */
function blockComment(stream: StringStream, state: ProgramState): string {
    if (stream.skipTo('*/')) {
        stream.match('*/')
        state.comment = false
    } else {
        stream.skipToEnd()
    }
    return 'comment'
}

/** What a word is: a member after a dot, a function before a parenthesis, else a keyword or a name. */
function word(
    stream: StringStream,
    state: ProgramState,
    text: string,
    keywords: ReadonlySet<string>,
): string {
    const called = stream.match(/^\s*\(/, false) !== null
    if (state.member) return called ? 'variableName.function' : 'propertyName'
    if (keywords.has(text)) {
        if (text === 'true' || text === 'false') return 'bool'
        if (text === 'null') return 'null'
        return 'keyword'
    }
    return called ? 'variableName.function' : 'variableName'
}

/** One token of either language: what the two share, with the parts that differ handed in. */
function programToken(
    stream: StringStream,
    state: ProgramState,
    language: {
        keywords: ReadonlySet<string>
        operator: RegExp
        punctuation: RegExp
        number: RegExp
        quotedName: RegExp
        binding: RegExp | null
    },
): string | null {
    if (state.comment) return blockComment(stream, state)
    if (stream.eatSpace()) return null
    const member = state.member
    state.member = false
    if (stream.match('//')) {
        stream.skipToEnd()
        return 'comment'
    }
    if (stream.match('/*')) {
        state.comment = true
        return blockComment(stream, state)
    }
    if (stream.match(/^'(?:[^'\\]|\\.)*'/)) return 'string'
    if (stream.match(/^'(?:[^'\\]|\\.)*$/)) return 'invalid'
    if (stream.match(language.quotedName)) return 'variableName'
    if (language.binding !== null && stream.match(language.binding)) return 'variableName.special'
    if (stream.match(TEMPORAL)) return 'number'
    const name = stream.match(NAME) as RegExpMatchArray | null
    if (name !== null) return word(stream, { ...state, member }, name[0], language.keywords)
    if (stream.match(language.number)) return 'number'
    if (stream.match(/^[{}()[\]]/)) return 'bracket'
    if (stream.match(language.operator)) return 'operator'
    if (stream.eat('.')) {
        state.member = true
        return 'punctuation'
    }
    if (stream.match(language.punctuation)) return 'punctuation'
    stream.next()
    return 'invalid'
}

/** The words FHIRPath's grammar spells as operators and literals. */
const FHIRPATH_KEYWORDS: ReadonlySet<string> = new Set([
    'and',
    'or',
    'xor',
    'implies',
    'is',
    'as',
    'div',
    'mod',
    'in',
    'contains',
    'true',
    'false',
])

/**
 * FHIRPath: a name followed by `(` is a function, a name after `.` is a member even when it is
 * spelled like a keyword, `%name` and `$this` are bound from outside the expression, a backticked
 * name is a name, and a single-quoted text is a string.
 */
export const fhirpathParser: StreamParser<ProgramState> & { name: string } = {
    name: 'fhirpath',
    startState: () => ({ comment: false, member: false }),
    copyState: (state) => ({ ...state }),
    token: (stream, state) =>
        programToken(stream, state, {
            keywords: FHIRPATH_KEYWORDS,
            operator: /^(?:!=|!~|<=|>=|[=~<>+\-*/&|])/,
            punctuation: /^,/,
            number: /^\d+(?:\.\d+)?/,
            quotedName: /^`(?:[^`\\]|\\.)*`/,
            binding: /^(?:%(?:[A-Za-z_]\w*|`(?:[^`\\]|\\.)*`|'(?:[^'\\]|\\.)*')|\$(?:this|index|total)\b)/,
        }),
    languageData: {
        commentTokens: { line: '//', block: { open: '/*', close: '*/' } },
        closeBrackets: { brackets: ['(', '[', '{', "'", '`'] },
    },
}

/** The words CQL's grammar spells, lower case as the language is. */
const CQL_KEYWORDS: ReadonlySet<string> = new Set([
    'after',
    'aggregate',
    'all',
    'and',
    'as',
    'asc',
    'ascending',
    'before',
    'between',
    'by',
    'called',
    'case',
    'cast',
    'code',
    'codesystem',
    'codesystems',
    'collapse',
    'concept',
    'contains',
    'context',
    'convert',
    'date',
    'day',
    'days',
    'default',
    'define',
    'desc',
    'descending',
    'difference',
    'display',
    'distinct',
    'div',
    'duration',
    'during',
    'else',
    'end',
    'ends',
    'except',
    'exists',
    'expand',
    'false',
    'flatten',
    'fluent',
    'from',
    'function',
    'hour',
    'hours',
    'if',
    'implies',
    'in',
    'include',
    'included',
    'includes',
    'intersect',
    'is',
    'let',
    'library',
    'maximum',
    'meets',
    'millisecond',
    'milliseconds',
    'minimum',
    'minute',
    'minutes',
    'mod',
    'month',
    'months',
    'not',
    'null',
    'occurs',
    'of',
    'on',
    'or',
    'overlaps',
    'parameter',
    'per',
    'point',
    'predecessor',
    'private',
    'properly',
    'public',
    'return',
    'returns',
    'same',
    'second',
    'seconds',
    'singleton',
    'sort',
    'start',
    'starting',
    'starts',
    'successor',
    'such',
    'than',
    'that',
    'then',
    'time',
    'timezoneoffset',
    'to',
    'true',
    'union',
    'using',
    'valueset',
    'version',
    'week',
    'weeks',
    'when',
    'where',
    'width',
    'with',
    'within',
    'without',
    'xor',
    'year',
    'years',
])

/**
 * CQL: a single-quoted text is a string, a double-quoted or backticked one is a name, a name
 * followed by `(` is a function, a name after `.` is a member even when it is spelled like a
 * keyword, and `@2026-01-01` is a date.
 */
export const cqlParser: StreamParser<ProgramState> & { name: string } = {
    name: 'cql',
    startState: () => ({ comment: false, member: false }),
    copyState: (state) => ({ ...state }),
    token: (stream, state) =>
        programToken(stream, state, {
            keywords: CQL_KEYWORDS,
            operator: /^(?:!=|!~|<=|>=|[=~<>+\-*/&|^])/,
            punctuation: /^[,:]/,
            number: /^\d+(?:\.\d+|L)?/,
            quotedName: /^(?:"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`)/,
            binding: null,
        }),
    languageData: {
        commentTokens: { line: '//', block: { open: '/*', close: '*/' } },
        closeBrackets: { brackets: ['(', '[', '{', "'", '"', '`'] },
    },
}
