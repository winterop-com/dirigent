/** Monaco's helper that starts a language worker by label; the package ships no types for it. */
declare module 'monaco-editor/internal/common/workers' {
    import type { editor } from 'monaco-editor/editor/editor.api'

    export function createWebWorker<T extends object>(options: {
        label?: string
        moduleId: string
        createData?: unknown
        host?: Record<string, (...args: unknown[]) => unknown>
        keepIdleModels?: boolean
        createWorker?: () => Worker
    }): editor.MonacoWebWorker<T>
}

/** Monaco's Monarch compiler, which the tokeniser tests run a grammar through. */
declare module 'monaco-editor/editor/standalone/common/monarch/monarchCompile' {
    import type { languages } from 'monaco-editor/editor/editor.api'

    export function compile(languageId: string, json: languages.IMonarchLanguage): unknown
}

/** Monaco's Monarch tokeniser, which reads a compiled grammar one line at a time. */
declare module 'monaco-editor/editor/standalone/common/monarch/monarchLexer' {
    import type { languages } from 'monaco-editor/editor/editor.api'

    export class MonarchTokenizer {
        constructor(
            languageService: unknown,
            themeService: unknown,
            languageId: string,
            lexer: unknown,
            configurationService: unknown,
        )
        getInitialState(): languages.IState
        tokenize(
            line: string,
            hasEOL: boolean,
            state: languages.IState,
        ): { tokens: { offset: number; type: string }[]; endState: languages.IState }
    }
}
