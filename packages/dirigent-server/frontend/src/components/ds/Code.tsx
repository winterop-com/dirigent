import { cn } from '@/lib/utils'

/** Which ink a code is drawn in: muted beside a title, the body ink where it is the value itself. */
export type CodeTone = 'muted' | 'body'

const TONES: Record<CodeTone, string> = {
    muted: 'text-muted-foreground',
    body: 'text-foreground',
}

/**
 * A code, a key, a block or a kind, in mono on one line.
 *
 * It never wraps mid-word: where it does not fit it truncates with an ellipsis and carries the
 * whole value on `title`, so what is copied off the screen is always the string itself.
 */
export function Code({
    value,
    tone = 'muted',
    className,
}: {
    value: string
    tone?: CodeTone
    className?: string
}) {
    return (
        <code
            className={cn(
                'inline-block max-w-full min-w-0 truncate align-bottom font-mono text-xs whitespace-nowrap',
                TONES[tone],
                className,
            )}
            title={value}
        >
            {value}
        </code>
    )
}
