import { useId, type ReactNode } from 'react'

import { CopyButton } from '@winterop-com/sokkel-ui/CopyButton'
import { GroupLabel } from '@winterop-com/sokkel-ui/GroupLabel'

import { copyWords } from '@/lib/design-system'

/** One headed group of a side panel: its label, how many it holds where it holds any, and the group. */
export function PanelGroup({
    title,
    count,
    children,
}: {
    title: string
    count?: number
    children: ReactNode
}) {
    const headingId = useId()
    return (
        <section aria-labelledby={headingId} className="space-y-2">
            <div className="flex items-baseline gap-2">
                <GroupLabel as="h3">
                    <span id={headingId}>{title}</span>
                </GroupLabel>
                {count !== undefined && count > 0 && (
                    <span className="font-mono text-xs text-muted-foreground">{count}</span>
                )}
            </div>
            {children}
        </section>
    )
}

/** A machine's string beside the button that copies it. */
export function Copyable({ value, label }: { value: string; label: string }) {
    return (
        <span className="flex items-start gap-1">
            <span className="identifier">{value}</span>
            <CopyButton value={value} size="icon-xs" words={copyWords(label)} />
        </span>
    )
}
