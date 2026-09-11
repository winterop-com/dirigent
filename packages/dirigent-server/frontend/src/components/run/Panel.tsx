import { Check, Copy } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'

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

/** How long the button says it copied before it goes back to offering to. */
const CONFIRM_MS = 1200

/**
 * A machine's string beside the button that copies it.
 *
 * A trace id is pasted into another system rather than read aloud, so what it needs is to be
 * exact and to be taken in one gesture. The clipboard is not always available -- an insecure
 * origin has none -- and a refusal leaves the string itself, which is still selectable.
 */
export function Copyable({ value, label }: { value: string; label: string }) {
    const [copied, setCopied] = useState(false)
    return (
        <span className="flex items-start gap-1">
            <span className="identifier">{value}</span>
            <Button
                variant="ghost"
                size="icon-xs"
                aria-label={label}
                onClick={() => {
                    void navigator.clipboard?.writeText(value).then(
                        () => {
                            setCopied(true)
                            setTimeout(() => {
                                setCopied(false)
                            }, CONFIRM_MS)
                        },
                        () => {
                            // No clipboard on this origin. The string is on screen either way.
                        },
                    )
                }}
            >
                {copied ? <Check className="size-3" aria-hidden /> : <Copy className="size-3" aria-hidden />}
            </Button>
        </span>
    )
}
