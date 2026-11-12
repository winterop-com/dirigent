import type { ReactNode } from 'react'

import { CopyButton } from '@winterop-com/sokkel-ui/CopyButton'

import { copyWords } from '@/lib/design-system'

/** One labelled fact, as a row of a two-column definition list. */
export function Fact({ term, detail }: { term: string; detail: ReactNode }) {
    return (
        <>
            <dt className="text-faint">{term}</dt>
            <dd className="break-words text-foreground">{detail}</dd>
        </>
    )
}

/** One headed block of the panel. */
export function Section({ title, children }: { title: string; children: ReactNode }) {
    return (
        <section className="space-y-2">
            <h2 className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">{title}</h2>
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
