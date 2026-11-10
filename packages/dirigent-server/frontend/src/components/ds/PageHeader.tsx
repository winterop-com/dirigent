import type { ReactNode } from 'react'

import { Breadcrumb, type Crumb } from '@/components/Breadcrumb'
import { Code } from '@/components/ds/Code'
import { PageHead } from '@/components/PageHead'
import { ToolbarActions, type ToolbarAction } from '@/components/ToolbarActions'
import { PageHeader as LibraryPageHeader } from '@winterop-com/sokkel-ui/PageHeader'

/**
 * A screen's heading, sokkel-ui's `PageHeader` drawn into the shell's head slot: the title, the
 * code under it on a screen that is one thing, and the screen's verbs opposite it.
 *
 * The verbs are a measured `ToolbarActions` in the room the title leaves, so the title is never
 * cut: they fold into one menu before it would be. The last of `actions` is the primary, and one
 * carrying `more` is drawn as a `SplitButton`. `count` sits beside the title -- how many rows the
 * listing holds -- and `aside` stands before the verbs. There is no subtitle. `trail` is drawn by
 * `Breadcrumb` in the shell's top strip.
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
    const verbs =
        actions === undefined ? (
            aside
        ) : (
            <div className="flex min-h-9 min-w-0 items-center justify-end">
                <ToolbarActions actions={actions} lead={aside} measured />
            </div>
        )
    return (
        <PageHead inPlace={inPlace}>
            {trail !== undefined && <Breadcrumb trail={trail} />}
            <div className="mb-6">
                <LibraryPageHeader
                    title={title}
                    count={count}
                    meta={code === undefined || code === null ? undefined : <Code value={code} />}
                    actions={verbs}
                    actionsFill={actions !== undefined}
                />
            </div>
        </PageHead>
    )
}
