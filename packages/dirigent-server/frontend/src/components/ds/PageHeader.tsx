import type { ReactNode } from 'react'

import { Breadcrumb, type Crumb } from '@/components/Breadcrumb'
import { ToolbarActions, type ToolbarAction } from '@/components/ToolbarActions'

/**
 * A screen's heading: the title, or a trail for a screen that is one thing, and the screen's
 * verbs opposite it.
 *
 * The title is never cut: the verbs fold into one menu before it would be. The last of
 * `actions` is the primary, and one carrying `more` is drawn as a `SplitButton`. `count` sits
 * beside the title in small ink -- how many rows the listing holds -- and `aside` stands before
 * the verbs. There is no subtitle: a screen carries none.
 *
 * Given `trail`, the heading is the trail with its leaf as the screen's accessible title, and
 * `code` is drawn after it in mono.
 */
export function PageHeader({
    title,
    count,
    aside,
    actions,
    trail,
    code,
}: {
    title: string
    count?: ReactNode
    aside?: ReactNode
    /** The screen's verbs, primary last, which collapse into one menu below the breakpoint. */
    actions?: readonly ToolbarAction[]
    trail?: readonly Crumb[]
    code?: string | null
}) {
    return (
        <div className="mb-6 flex min-h-8 flex-nowrap items-center justify-between gap-4">
            {trail === undefined ? (
                <div className="flex shrink-0 items-baseline gap-2">
                    <h1 className="text-base font-semibold tracking-tight whitespace-nowrap">{title}</h1>
                    {count !== undefined && (
                        <span className="text-xs text-muted-foreground tabular-nums">{count}</span>
                    )}
                </div>
            ) : (
                <div className="min-w-0">
                    <h1 className="sr-only">{title}</h1>
                    <Breadcrumb trail={trail} code={code} />
                </div>
            )}
            {(aside !== undefined || actions !== undefined) && (
                <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
                    {aside}
                    {actions !== undefined && <ToolbarActions actions={actions} measured />}
                </div>
            )}
        </div>
    )
}
