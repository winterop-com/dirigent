import { Suspense, lazy, type ComponentProps } from 'react'

import type { CodeEditor as Editor } from '@/components/pipeline/CodeEditor'
import { whenIdle } from '@/lib/idle'
import { cn } from '@/lib/utils'

/**
 * The one door to Monaco, which is the only way in for every screen that writes source.
 *
 * ONE DYNAMIC IMPORT, ONE CHUNK. Monaco and its two workers are larger than the whole of the
 * rest of this bundle, and three places need them -- the editor's source pane, the apply dialog
 * on the listing, and a step config field whose schema says it carries a program. All three
 * mount this, so the editor, its schema wiring and its workers are fetched once and no screen
 * holds a copy of the arrangement.
 *
 * IT IS WARMED WHILE NOBODY IS WAITING. `warmEditor` is that same import, fired from the shell
 * once the browser is idle, so the first source tab, apply dialog or jq step of a session opens
 * against a chunk that is already there. A warm that fails costs nothing: the real import asks
 * again and reports what happened.
 *
 * THE FALLBACK IS THE EDITOR'S OWN BOX, carrying the height its caller asked for, so what is
 * around the pane is the same size before the chunk lands and after.
 */
const load = () => import('@/components/pipeline/CodeEditor')

const CodeEditor = lazy(() => load().then((module) => ({ default: module.CodeEditor })))

/** Whether the chunk has already been asked for, because asking twice warms nothing. */
let warmed = false

/** Fetch the editor's chunk while the browser has nothing better to do. */
export function warmEditor(): void {
    if (warmed) return
    warmed = true
    whenIdle(() => {
        void load().catch(() => undefined)
    })
}

export function CodePane({ className, ...rest }: ComponentProps<typeof Editor>) {
    return (
        <Suspense
            fallback={
                <p className={cn('text-muted-foreground h-full min-h-64 w-full p-4 text-sm', className)}>
                    Loading the editor.
                </p>
            }
        >
            <CodeEditor className={className} {...rest} />
        </Suspense>
    )
}
