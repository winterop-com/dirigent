import { Link } from 'react-router'

import { headingOf } from '@/lib/identity'
import { cn } from '@/lib/utils'

/**
 * A reference to a pipeline from a row or a panel that is about something else.
 *
 * TITLE ELSE CODE, AND THE CODE ALWAYS ON SCREEN. The name where the pipeline has one, with the
 * code beside or under it in mono; where it has none the code is the title and wears the mono
 * face itself, so it is never drawn twice.
 *
 * The link stops its click at itself, because the row it sits in opens something of its own.
 */
export function PipelineRef({
    code,
    name,
    inline = false,
}: {
    code: string
    name: string | null
    /** One line with the code after the title, rather than the code on a line of its own. */
    inline?: boolean
}) {
    const heading = headingOf({ code, name })
    return (
        <span
            data-testid="pipeline-ref"
            className={cn('flex min-w-0', inline ? 'items-baseline gap-2 text-xs' : 'flex-col')}
        >
            <Link
                className={cn(
                    'truncate',
                    inline ? 'text-muted-foreground hover:text-foreground' : 'hover:text-primary',
                    !heading.named && 'font-mono',
                )}
                to={`/pipelines/${encodeURIComponent(code)}`}
                title={heading.title}
                onClick={(event) => {
                    event.stopPropagation()
                }}
            >
                {heading.title}
            </Link>
            {heading.code !== null && (
                <span className="truncate font-mono text-xs text-muted-foreground" title={heading.code}>
                    {heading.code}
                </span>
            )}
        </span>
    )
}
