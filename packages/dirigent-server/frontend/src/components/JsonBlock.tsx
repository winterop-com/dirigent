import { useMemo } from 'react'

import { CodeWindow } from '@/components/CodeWindow'
import { tokenizeJson, type JsonTokenKind } from '@/lib/json-tokens'
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
 */
export function JsonBlock({ title, text, className }: { title: string; text: string; className?: string }) {
    const tokens = useMemo(() => tokenizeJson(text), [text])
    return (
        <div className="relative">
            <pre
                className={cn(
                    'overflow-auto rounded-lg border border-border bg-background p-2 font-mono text-xs',
                    className,
                )}
            >
                {tokens.map((token, at) => (
                    // The list is stable for a given text, so the position is the identity.
                    // oxlint-disable-next-line no-array-index-key
                    <span key={at} className={HUES[token.kind]}>
                        {token.text}
                    </span>
                ))}
            </pre>
            <CodeWindow title={title} text={text} mediaType="application/json" path={`window/${title}`} />
        </div>
    )
}
