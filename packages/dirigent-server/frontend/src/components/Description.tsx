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

/** A description reads as a hint beside a title; a whole document, such as a run's report, reads as body. */
export type DescriptionInk = 'hint' | 'body'

export function Description({ text, ink = 'hint' }: { text: string | null; ink?: DescriptionInk }) {
    if (text === null || text.trim() === '') return null
    const colour = ink === 'hint' ? 'text-muted-foreground' : 'text-foreground'
    return (
        <Suspense fallback={<p className={`${colour} text-sm`}>{oneLine(text)}</p>}>
            <div className={colour}>
                <Markdown text={text} />
            </div>
        </Suspense>
    )
}
