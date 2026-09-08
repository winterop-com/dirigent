import { Loader2, ServerCrash } from 'lucide-react'
import type { ReactNode } from 'react'

import { ToolbarActions, type ToolbarAction } from '@/components/ToolbarActions'
import { Card, CardContent } from '@/components/ui/card'
import type { Problem } from '@/lib/api'
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
                <CardContent className="text-muted-foreground flex items-center gap-2 py-2 text-sm">
                    <Loader2 className="size-4 animate-spin" aria-hidden />
                    Reading from the server
                </CardContent>
            </Card>
        )
    }
    if (problem !== null) {
        const lines = refusalLines(problem)
        return (
            <Card>
                <CardContent className="flex items-start gap-3 py-8">
                    <ServerCrash className="text-destructive mt-0.5 size-4 shrink-0" aria-hidden />
                    <div className="space-y-1">
                        <p className="text-sm font-medium">{problem.title}</p>
                        {lines.detail !== null && (
                            <p className="text-muted-foreground text-xs break-words">{lines.detail}</p>
                        )}
                        {lines.problems.length > 0 && (
                            <ul className="text-muted-foreground list-disc space-y-0.5 pl-4 text-xs">
                                {lines.problems.map((one) => (
                                    <li key={one} className="font-mono break-all">
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
                <CardContent className="text-muted-foreground py-2 text-sm">{emptyMessage}</CardContent>
            </Card>
        )
    }
    return <>{children}</>
}

/**
 * A page's heading, one line saying what the page is for, and whatever the page states beside it.
 *
 * `aside` sits opposite the title on the same baseline, which is where a page's metadata about
 * itself belongs. It stays outside the heading element, so the heading's accessible name is the
 * title alone.
 */
export function PageHeader({
    title,
    description,
    aside,
    actions,
}: {
    title: string
    /** The line under the title; a screen whose title says the whole thing carries none. */
    description?: string
    aside?: ReactNode
    /** The screen's verbs, which collapse into one menu below the breakpoint. */
    actions?: readonly ToolbarAction[]
}) {
    return (
        <div className="mb-6 flex flex-nowrap items-start justify-between gap-4">
            <div className="min-w-0 space-y-1">
                <h1 className="truncate text-base font-semibold tracking-tight">{title}</h1>
                {description !== undefined && <p className="text-muted-foreground text-sm">{description}</p>}
            </div>
            {(aside !== undefined || actions !== undefined) && (
                <div className="flex shrink-0 items-center gap-2 pt-1">
                    {aside}
                    {actions !== undefined && <ToolbarActions actions={actions} />}
                </div>
            )}
        </div>
    )
}
