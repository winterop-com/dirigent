import { useMemo } from 'react'

import { CodePane } from '@/components/pipeline/CodePane'
import { WindowedPane } from '@/components/WindowedPane'
import { tokenizeJson, type JsonTokenKind } from '@/lib/json-tokens'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/** The colour each kind of piece wears, from the palette the rest of the screen is drawn in. */
const HUES: Record<JsonTokenKind, string | undefined> = {
    key: 'text-info-ink',
    string: 'text-good-ink',
    number: 'text-warning-ink',
    literal: 'text-warning-ink',
    punctuation: 'text-muted-foreground',
}

/**
 * One piece of JSON on a screen: coloured where it stands, and a window when that is small.
 *
 * The box is sized for the common case and coloured by its own tokens rather than an
 * editor, so it costs nothing to draw beside every step. The window is the same text a
 * size up, in the read-only editor -- folding and search are what a large value needs,
 * and the box's job is only to be legible.
 *
 * IT IS A PREVIEW, SO IT DECLARES A HEIGHT, AND THE HEIGHT IS STATED HERE. Reference material
 * has no length of its own: a block drawn at the height of what it holds pushes whatever acts on
 * it below the fold, so this is a pane of seventeen lines and the window carries the rest. A
 * surface with less room to give narrows it through `className` and says what it measured;
 * nothing leaves it off.
 *
 * `className` sizes the scrolling text; the window button's strip is under it, inside the box,
 * so the one control here is never the part a height cuts off.
 */
export function JsonBlock({ title, text, className }: { title: string; text: string; className?: string }) {
    const tokens = useMemo(() => tokenizeJson(text), [text])
    return (
        <WindowedPane
            name={title}
            className="rounded-lg border border-border bg-background"
            windowed={
                <CodePane
                    value={text}
                    mediaType="application/json"
                    path={`window/${title}`}
                    label={LABELS.shell.in_window(title)}
                    readOnly
                    className="min-h-0 flex-1"
                />
            }
        >
            <pre className={cn('max-h-72 overflow-auto rounded-t-lg p-2 font-mono text-xs', className)}>
                {tokens.map((token, at) => (
                    // The list is stable for a given text, so the position is the identity.
                    // oxlint-disable-next-line no-array-index-key
                    <span key={at} className={HUES[token.kind]}>
                        {token.text}
                    </span>
                ))}
            </pre>
        </WindowedPane>
    )
}
