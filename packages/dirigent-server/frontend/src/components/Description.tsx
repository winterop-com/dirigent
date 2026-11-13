import { Suspense, lazy } from 'react'

import { DESCRIPTION_MARKDOWN } from '@/lib/design-system'
import { oneLine } from '@/lib/identity'

/**
 * What a thing says about itself, wherever there is room for the whole of it.
 *
 * THE RENDERER IS ITS OWN CHUNK. A description is markdown, drawn by sokkel-ui's `PlainMarkdown`,
 * and its parser arrives when a description is first drawn, never on a screen with none.
 *
 * THE FALLBACK IS THE TEXT. While the chunk is arriving, the description is drawn as the words
 * it is written in: readable, inert, and the same sentence the rendered form will say.
 *
 * NO HTML STRING IS EVER HANDED TO THE DOM. `PlainMarkdown` builds React elements from a syntax
 * tree and shows raw markup as typed, so a `<script>` in a description becomes nothing that runs.
 * Raw HTML is never allowed here.
 *
 * NOTHING IN A DESCRIPTION REACHES OUT. An image is drawn as its alt text and address and is never
 * fetched, and a link is live only to an https address or a mailbox; any other link is its words.
 *
 * A DESCRIPTION'S HEADINGS SIT UNDER ITS OWN. `under` is the level of the heading the description
 * is set beneath, and a `#` in the text becomes the level below it.
 *
 * A FIELD'S HELP IS ONE LINE. At the help size the text is drawn inline, as runs inside one
 * paragraph, with no blocks of its own.
 *
 * A LISTING ROW USES NEITHER. One truncated line of raw text is what a row has space for, and
 * `oneLine` in `lib/identity` is what it truncates.
 */
const PlainMarkdown = lazy(() =>
    import('@winterop-com/sokkel-ui/PlainMarkdown').then((module) => ({ default: module.PlainMarkdown })),
)

/** A description reads as a hint beside a title; a whole document, such as a run's report, reads as body. */
export type DescriptionInk = 'hint' | 'body'

/** A description is set at body size; a field's help is the smaller size under its control, on one line. */
export type DescriptionSize = 'body' | 'help'

/** The level of the heading a description sits under: a page's title, or a panel's or a dialog's. */
export type DescriptionUnder = 1 | 2 | 3

export function Description({
    text,
    ink = 'hint',
    size = 'body',
    under = 2,
}: {
    text: string | null
    ink?: DescriptionInk
    size?: DescriptionSize
    under?: DescriptionUnder
}) {
    if (text === null || text.trim() === '') return null
    const colour = ink === 'hint' ? 'text-muted-foreground' : 'text-foreground'
    if (size === 'help') {
        const set = `${colour} text-xs`
        return (
            <p className={set}>
                <Suspense fallback={oneLine(text)}>
                    <PlainMarkdown content={text} className={set} {...DESCRIPTION_MARKDOWN} inline />
                </Suspense>
            </p>
        )
    }
    const set = `${colour} text-sm`
    return (
        <Suspense fallback={<p className={set}>{oneLine(text)}</p>}>
            <PlainMarkdown content={text} className={set} {...DESCRIPTION_MARKDOWN} headingOffset={under} />
        </Suspense>
    )
}
