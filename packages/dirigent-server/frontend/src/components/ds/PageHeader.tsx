import type { ReactNode } from 'react'

import { Breadcrumb, type Crumb } from '@/components/Breadcrumb'
import { PageHead } from '@/components/PageHead'
import { TOOLBAR_WORDS } from '@/lib/design-system'
import { PageHeader as LibraryPageHeader } from '@winterop-com/sokkel-ui/PageHeader'
import type { ToolbarItem } from '@winterop-com/sokkel-ui/Toolbar'

/**
 * A screen's heading, sokkel-ui's `PageHeader` drawn into the shell's head slot: the title, the
 * code under it on a screen that is one thing, and the screen's verbs opposite it.
 *
 * `items` are the verbs that fold, from the last, into "More actions" where the room the title
 * leaves cannot hold them, so they never crowd the title; a title that is the code is cut short with
 * the whole of it on hover. `primary` stands after them, filled, and never folds. The row draws every verb by its word alone; More lists them with their marks.
 * `lead` stands before the verbs and never folds either. `count` sits beside the title -- how many
 * rows the listing holds -- and `meta` is a line of small facts under it. There is no subtitle.
 * `trail` is drawn by `Breadcrumb` in the shell's top strip.
 */
export function PageHeader({
    title,
    count,
    lead,
    items,
    primary,
    trail,
    code,
    meta,
    inPlace = false,
}: {
    title: string
    count?: ReactNode
    lead?: ReactNode
    items?: readonly ToolbarItem[]
    primary?: ToolbarItem
    trail?: readonly Crumb[]
    code?: string | null
    meta?: ReactNode
    /** Drawn where it is rendered rather than in the shell's head, as the gallery does. */
    inPlace?: boolean
}) {
    return (
        <PageHead inPlace={inPlace}>
            {trail !== undefined && <Breadcrumb trail={trail} />}
            <div className="mb-6 *:min-h-9">
                <LibraryPageHeader
                    title={title}
                    count={count}
                    code={code ?? undefined}
                    meta={meta}
                    lead={lead}
                    items={items}
                    primary={primary}
                    wordsOnly
                    words={TOOLBAR_WORDS}
                />
            </div>
        </PageHead>
    )
}
