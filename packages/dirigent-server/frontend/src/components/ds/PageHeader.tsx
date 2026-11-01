import type { ReactNode } from 'react'

import { Breadcrumb, type Crumb } from '@/components/Breadcrumb'
import { Code } from '@/components/ds/Code'
import { PageHead } from '@/components/PageHead'
import { ToolbarActions, type ToolbarAction } from '@/components/ToolbarActions'
import { cn } from '@/lib/utils'

/**
 * A screen's heading: the title, the code under it on a screen that is one thing, and the
 * screen's verbs opposite it.
 *
 * The title is never cut: the verbs fold into one menu before it would be. The last of
 * `actions` is the primary, and one carrying `more` is drawn as a `SplitButton`. `count` sits
 * beside the title in small ink -- how many rows the listing holds -- and `aside` stands before
 * the verbs. There is no subtitle: a screen carries none. `trail` is drawn by `Breadcrumb` in the
 * shell's top strip.
 */
export function PageHeader({
    title,
    count,
    aside,
    actions,
    trail,
    code,
    inPlace = false,
}: {
    title: string
    count?: ReactNode
    aside?: ReactNode
    /** The screen's verbs, primary last, which collapse into one menu below the breakpoint. */
    actions?: readonly ToolbarAction[]
    trail?: readonly Crumb[]
    code?: string | null
    /** Drawn where it is rendered rather than in the shell's head, as the gallery does. */
    inPlace?: boolean
}) {
    return (
        <PageHead inPlace={inPlace}>
            <div
                className={cn(
                    'mb-6 flex min-h-9 flex-nowrap justify-between gap-4',
                    code === undefined || code === null ? 'items-center' : 'items-start',
                )}
            >
                {trail !== undefined && <Breadcrumb trail={trail} />}
                <div className="min-w-0 shrink-0">
                    <div className="flex items-baseline gap-2">
                        <h1 className="text-page font-medium tracking-tight whitespace-nowrap">{title}</h1>
                        {count !== undefined && (
                            <span className="text-xs text-muted-foreground tabular-nums">{count}</span>
                        )}
                    </div>
                    {code !== undefined && code !== null && (
                        <div className="mt-1.5">
                            <Code value={code} />
                        </div>
                    )}
                </div>
                {(aside !== undefined || actions !== undefined) && (
                    <div className="flex min-h-9 min-w-0 flex-1 items-center justify-end gap-2">
                        {actions === undefined ? (
                            aside
                        ) : (
                            <ToolbarActions actions={actions} lead={aside} measured />
                        )}
                    </div>
                )}
            </div>
        </PageHead>
    )
}
