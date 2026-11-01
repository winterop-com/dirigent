import type * as monaco from 'monaco-editor/editor/editor.api'

/**
 * The program languages monaco ships no grammar for, each as a Monarch tokeniser.
 *
 * Every grammar here names its tokens from the same few classes, which the house theme in
 * `CodeEditor` colours: `keyword`, `number`, `string`, `comment`, `delimiter`, `type` for a
 * function or a path, `variable.binding` for a name bound outside the program, and `identifier`
 * for every other name.
 */

/** One grammar, as `CodeEditor` registers it with monaco. */
export interface ProgramGrammar {
    id: string
    extension: string
    language: monaco.languages.IMonarchLanguage
    configuration: monaco.languages.LanguageConfiguration
}

/** The words jq's own grammar spells: everything that is syntax rather than a function. */
const JQ_KEYWORDS = [
    'def',
    'if',
    'then',
    'elif',
    'else',
    'end',
    'as',
    'reduce',
    'foreach',
    'try',
    'catch',
    'label',
    'import',
    'include',
    'and',
    'or',
    'not',
]

/** The jq builtins a program reaches for, which read as functions rather than as names. */
const JQ_BUILTINS = [
    'map',
    'select',
    'length',
    'keys',
    'values',
    'has',
    'in',
    'to_entries',
    'from_entries',
    'with_entries',
    'add',
    'any',
    'all',
    'flatten',
    'range',
    'floor',
    'sqrt',
    'pow',
    'log',
    'tostring',
    'tonumber',
    'type',
    'infinite',
    'nan',
    'sort',
    'sort_by',
    'group_by',
    'unique',
    'unique_by',
    'min',
    'max',
    'min_by',
    'max_by',
    'reverse',
    'contains',
    'inside',
    'startswith',
    'endswith',
    'ltrimstr',
    'rtrimstr',
    'explode',
    'implode',
    'split',
    'join',
    'ascii_downcase',
    'ascii_upcase',
    'recurse',
    'env',
    'input',
    'inputs',
    'debug',
    'stderr',
    'input_filename',
    'splits',
    'sub',
    'gsub',
    'test',
    'match',
    'capture',
    'scan',
    'ascii',
    'todate',
    'fromdate',
    'now',
    'dateadd',
    'datesub',
    'date',
    'tojson',
    'fromjson',
    'getpath',
    'setpath',
    'delpaths',
    'paths',
    'leaf_paths',
    'first',
    'last',
    'nth',
    'until',
    'limit',
    'while',
    'repeat',
    'isvalid',
    'error',
    'halt',
    'halt_error',
]

/**
 * jq: `.field` and `.[` as the keys they name, `$name` as a binding, and a `\(...)` inside a
 * string as the program again, which is why the string state re-enters `@root`.
 */
const JQ_LANGUAGE: monaco.languages.IMonarchLanguage = {
    defaultToken: '',
    keywords: JQ_KEYWORDS,
    builtins: JQ_BUILTINS,
    tokenizer: {
        root: [
            [/#.*$/, 'comment'],
            [/"/, { token: 'string', next: '@string' }],
            [/\$[A-Za-z_]\w*/, 'variable.binding'],
            [/\.\./, 'keyword'],
            [/\.[A-Za-z_]\w*/, 'type'],
            [/\.(?=\[)/, 'type'],
            [
                /[A-Za-z_]\w*/,
                { cases: { '@keywords': 'keyword', '@builtins': 'type', '@default': 'identifier' } },
            ],
            [/\d+\.\d+(?:[eE][-+]?\d+)?/, 'number.float'],
            [/\d+/, 'number'],
            [/[{}()[\]]/, '@brackets'],
            [/\|=|\/\/=?|==|!=|<=|>=|[-+*/%<>=]/, 'operator'],
            [/[|,;:?]/, 'delimiter'],
        ],
        string: [
            [/\\\(/, { token: 'delimiter', next: '@interpolation' }],
            [/\\./, 'string'],
            [/[^\\"]+/, 'string'],
            [/"/, { token: 'string', next: '@pop' }],
        ],
        interpolation: [[/\)/, { token: 'delimiter', next: '@pop' }], { include: '@root' }],
    },
}

/** A date, a time or a date-time written as a literal, `@2026-01-01T10:00:00Z` or `@T10:00`. */
const TEMPORAL =
    /@(?:T\d{2}(?::\d{2}(?::\d{2}(?:\.\d+)?)?)?|\d{4}(?:-\d{2}(?:-\d{2})?)?(?:T(?:\d{2}(?::\d{2}(?::\d{2}(?:\.\d+)?)?)?)?(?:Z|[+-]\d{2}:\d{2})?)?)/

/** A `/* ... *\/` comment, which may run over several lines. */
const BLOCK_COMMENT: monaco.languages.IMonarchLanguageRule[] = [
    [/[^*/]+/, 'comment'],
    [/\*\//, { token: 'comment', next: '@pop' }],
    [/[*/]/, 'comment'],
]

/** The words FHIRPath's grammar spells as operators and literals. */
const FHIRPATH_KEYWORDS = [
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
]

/**
 * FHIRPath: a name followed by `(` is a function, a name after `.` is a member even when it is
 * spelled like a keyword, `%name` and `$this` are bound from outside the
 * expression, a backticked name is a name, and a single-quoted text is a string.
 */
const FHIRPATH_LANGUAGE: monaco.languages.IMonarchLanguage = {
    defaultToken: '',
    keywords: FHIRPATH_KEYWORDS,
    tokenizer: {
        root: [
            [/\/\/.*$/, 'comment'],
            [/\/\*/, { token: 'comment', next: '@comment' }],
            [/'(?:[^'\\]|\\.)*'/, 'string'],
            [/'(?:[^'\\]|\\.)*$/, 'string.invalid'],
            [/`(?:[^`\\]|\\.)*`/, 'identifier'],
            [/%(?:[A-Za-z_]\w*|`(?:[^`\\]|\\.)*`|'(?:[^'\\]|\\.)*')/, 'variable.binding'],
            [/\$(?:this|index|total)\b/, 'variable.binding'],
            [TEMPORAL, 'number'],
            [/(\.)([A-Za-z_]\w*)(?=\s*\()/, ['delimiter', 'type']],
            [/(\.)([A-Za-z_]\w*)/, ['delimiter', 'identifier']],
            [/[A-Za-z_]\w*(?=\s*\()/, { cases: { '@keywords': 'keyword', '@default': 'type' } }],
            [/[A-Za-z_]\w*/, { cases: { '@keywords': 'keyword', '@default': 'identifier' } }],
            [/\d+\.\d+/, 'number.float'],
            [/\d+/, 'number'],
            [/[{}()[\]]/, '@brackets'],
            [/!=|!~|<=|>=|[=~<>+\-*/&|]/, 'operator'],
            [/[.,]/, 'delimiter'],
        ],
        comment: BLOCK_COMMENT,
    },
}

/** The words CQL's grammar spells, lower case as the language is. */
const CQL_KEYWORDS = [
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
]

/**
 * CQL: a single-quoted text is a string, a double-quoted or backticked one is a name, a name
 * followed by `(` is a function, a name after `.` is a member even when it is spelled like a
 * keyword, and `@2026-01-01` is a date.
 */
const CQL_LANGUAGE: monaco.languages.IMonarchLanguage = {
    defaultToken: '',
    keywords: CQL_KEYWORDS,
    tokenizer: {
        root: [
            [/\/\/.*$/, 'comment'],
            [/\/\*/, { token: 'comment', next: '@comment' }],
            [/'(?:[^'\\]|\\.)*'/, 'string'],
            [/'(?:[^'\\]|\\.)*$/, 'string.invalid'],
            [/"(?:[^"\\]|\\.)*"/, 'identifier'],
            [/`(?:[^`\\]|\\.)*`/, 'identifier'],
            [TEMPORAL, 'number'],
            [/(\.)([A-Za-z_]\w*)(?=\s*\()/, ['delimiter', 'type']],
            [/(\.)([A-Za-z_]\w*)/, ['delimiter', 'identifier']],
            [/[A-Za-z_]\w*(?=\s*\()/, { cases: { '@keywords': 'keyword', '@default': 'type' } }],
            [/[A-Za-z_]\w*/, { cases: { '@keywords': 'keyword', '@default': 'identifier' } }],
            [/\d+\.\d+/, 'number.float'],
            [/\d+L?/, 'number'],
            [/[{}()[\]]/, '@brackets'],
            [/!=|!~|<=|>=|[=~<>+\-*/&|^]/, 'operator'],
            [/[.,:]/, 'delimiter'],
        ],
        comment: BLOCK_COMMENT,
    },
}

/** Brackets and the pairs typing one of them closes, for a language whose strings are `quotes`. */
function configuration(
    lineComment: string,
    blockComment: [string, string] | null,
    quotes: string[],
): monaco.languages.LanguageConfiguration {
    return {
        comments: blockComment === null ? { lineComment } : { lineComment, blockComment },
        brackets: [
            ['{', '}'],
            ['[', ']'],
            ['(', ')'],
        ],
        autoClosingPairs: [
            { open: '{', close: '}' },
            { open: '[', close: ']' },
            { open: '(', close: ')' },
            ...quotes.map((quote) => ({ open: quote, close: quote })),
        ],
    }
}

export const PROGRAM_GRAMMARS: ProgramGrammar[] = [
    { id: 'jq', extension: 'jq', language: JQ_LANGUAGE, configuration: configuration('#', null, ['"']) },
    {
        id: 'fhirpath',
        extension: 'fhirpath',
        language: FHIRPATH_LANGUAGE,
        configuration: configuration('//', ['/*', '*/'], ["'", '`']),
    },
    {
        id: 'cql',
        extension: 'cql',
        language: CQL_LANGUAGE,
        configuration: configuration('//', ['/*', '*/'], ["'", '"', '`']),
    },
]
