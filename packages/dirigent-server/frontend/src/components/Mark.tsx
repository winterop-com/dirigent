import type { ReactElement } from 'react'

import type { Glyph } from '@/lib/glyphs'

/**
 * A kind's mark, at the one size and the one ink every glyph in this app is drawn in.
 *
 * What the mark sits in belongs to whatever draws it: a chip draws it bare, a picker's row
 * leads with it, a palette row gives it a tile.
 */
export function Mark({ glyph: Glyph }: { glyph: Glyph }): ReactElement {
    return <Glyph className="size-4 shrink-0 text-muted-foreground" aria-hidden data-slot="mark" />
}
