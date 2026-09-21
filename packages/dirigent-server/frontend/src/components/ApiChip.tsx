import { ExternalLink } from 'lucide-react'

import { API_LABEL, docsHref, type DocsTag } from '@/lib/docs'

/**
 * The way out of a screen and into the requests behind it.
 *
 * It is a plain anchor rather than a router link: `/docs` is the server's, not this bundle's,
 * and a new tab is what an escape hatch wants -- the reader is looking something up, not
 * leaving.
 *
 * `control-link` IS WHAT MAKES IT A FINGER TALL below the breakpoint, and the wider padding
 * there is what keeps a 42px tall box reading as a chip rather than a column.
 */
export function ApiChip({ tag }: { tag: DocsTag }) {
    return (
        <a
            className="control-link inline-flex items-center gap-1 rounded-sm border border-border px-3 py-0.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none md:px-1.5"
            href={docsHref(tag)}
            target="_blank"
            rel="noreferrer"
            title={`The ${tag} section of this instance's API documentation`}
        >
            {API_LABEL}
            <ExternalLink className="size-3" aria-hidden />
        </a>
    )
}
