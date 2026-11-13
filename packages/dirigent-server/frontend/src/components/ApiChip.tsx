import { Chip } from '@winterop-com/sokkel-ui/Chip'

import { LINK_WORDS } from '@/lib/design-system'
import { API_LABEL, docsHref, type DocsTag } from '@/lib/docs'
import { LABELS } from '@/lib/labels'

/**
 * The way out of a screen and into the requests behind it.
 *
 * An external link chip: `/docs` is the server's, not this bundle's, and a new tab is what an
 * escape hatch wants -- the reader is looking something up, not leaving. It stands alone in a
 * heading's strip, so it is a control's height, and a finger tall below the breakpoint.
 */
export function ApiChip({ tag }: { tag: DocsTag }) {
    return (
        <Chip
            tone="outline"
            size="control"
            href={docsHref(tag)}
            external
            title={LABELS.shell.api_docs(tag)}
            words={LINK_WORDS}
            className="text-muted-foreground"
        >
            {API_LABEL}
        </Chip>
    )
}
