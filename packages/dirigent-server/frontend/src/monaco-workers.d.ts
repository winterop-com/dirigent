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
