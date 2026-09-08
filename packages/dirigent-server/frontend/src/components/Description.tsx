import { Suspense, lazy } from 'react'

import { oneLine } from '@/lib/identity'

/**
 * What a thing says about itself, wherever there is room for the whole of it.
 *
 * THE RENDERER IS ITS OWN CHUNK. A description is markdown and reading markdown needs a lexer,
 * which is a dependency only the panes that draw one need -- so `components/Markdown` and the
 * lexer behind it arrive when a description is first drawn, and never on a screen with none.
 *
 * THE FALLBACK IS THE TEXT. While the chunk is arriving, the description is drawn as the words
 * it is written in: readable, inert, and the same sentence the rendered form will say.
 *
 * A LISTING ROW USES NEITHER. One truncated line of raw text is what a row has space for, and
 * `oneLine` in `lib/identity` is what it truncates -- rendering markdown into a cell that then
 * cuts it off would spend a chunk to draw half a heading.
 */
const Markdown = lazy(() => import('@/components/Markdown').then((module) => ({ default: module.Markdown })))

export function Description({ text }: { text: string | null }) {
    if (text === null || text.trim() === '') return null
    return (
        <Suspense fallback={<p className="text-muted-foreground text-sm">{oneLine(text)}</p>}>
            <div className="text-muted-foreground">
                <Markdown text={text} />
            </div>
        </Suspense>
    )
}
