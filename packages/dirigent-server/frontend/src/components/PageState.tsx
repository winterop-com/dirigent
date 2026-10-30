import { Loader2, ServerCrash } from 'lucide-react'
import type { ReactNode } from 'react'

import { Card, CardContent } from '@/components/ui/card'
import type { Problem } from '@/lib/api'
import { LABELS } from '@/lib/labels'
import { refusalLines } from '@/lib/refusal'

/**
 * The three states every read lands in, rendered the same way everywhere.
 *
 * The point is not the markup -- it is that "still reading", "the server refused", and "the
 * server answered with nothing" stay three distinct states all the way to the screen.
 * Collapsing the last two into one empty table is how an instance whose database is unreachable
 * gets told it has no pipelines, when what it has is no answer.
 *
 * THE REFUSAL IS A PROBLEM DOCUMENT, not a string. `title` is the status of the read that was
 * refused, which is what a whole screen becoming a card is about; `detail` is the sentence the
 * server wrote for a person to act on, and `problems` carries the individual failures when a
 * validation refused several things at once. `lib/refusal` decides which of the last two say
 * something the other does not.
 *
 * ALL THREE ARE ONE CARD, SO NONE OF THEM PADS ITSELF. The card's own 16px is the inset every
 * surface in this app holds its content at, and a `py-` laid over it is a second answer to a
 * question the card has already answered.
 */
export function PageState({
    loading,
    problem,
    empty,
    emptyMessage,
    children,
}: {
    loading: boolean
    /** What the server refused with, or null when it did not refuse. */
    problem: Problem | null
    empty: boolean
    /** The one line the empty card states. */
    emptyMessage?: ReactNode
    children: ReactNode
}) {
    if (loading) {
        return (
            <Card>
                <CardContent className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                    {LABELS.shell.reading}
                </CardContent>
            </Card>
        )
    }
    if (problem !== null) {
        const lines = refusalLines(problem)
        return (
            <Card>
                <CardContent className="flex items-start gap-2">
                    <ServerCrash className="mt-0.5 size-4 shrink-0 text-destructive" aria-hidden />
                    <div className="space-y-1">
                        <p className="text-sm font-medium">{problem.title}</p>
                        {lines.detail !== null && (
                            <p className="text-xs break-words text-muted-foreground">{lines.detail}</p>
                        )}
                        {lines.problems.length > 0 && (
                            <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                                {lines.problems.map((one) => (
                                    <li key={one} className="break-words">
                                        {one}
                                    </li>
                                ))}
                            </ul>
                        )}
                    </div>
                </CardContent>
            </Card>
        )
    }
    if (empty) {
        return (
            <Card>
                <CardContent className="text-sm text-muted-foreground">{emptyMessage}</CardContent>
            </Card>
        )
    }
    return <>{children}</>
}
