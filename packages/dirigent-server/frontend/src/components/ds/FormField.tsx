import type { ReactNode } from 'react'

import { Label } from '@/components/ui/label'
import { LABELS } from '@/lib/labels'
import { cn } from '@/lib/utils'

/**
 * One field: its label, the control the caller passes, and what is said around it.
 *
 * The label is prose, or a document key in mono (`mono`). Beside it, in this order: the
 * required word in body ink -- never amber, which is a link's -- a hint, and the default an
 * empty box submits. Under the control: help, and then the error, which replaces nothing. One
 * 6px gap between every line, and one ink for help.
 *
 * `id` is the control's: the label points at it, and the help and the error are named
 * `<id>-help` and `<id>-error` for the control's `aria-describedby`.
 */
export function FormField({
    id,
    label,
    mono = false,
    required = false,
    hint,
    fallback,
    help,
    error,
    children,
    className,
}: {
    id: string
    label: string
    mono?: boolean
    required?: boolean
    hint?: string
    /** What an empty box submits, already rendered as the document would write it. */
    fallback?: string
    help?: ReactNode
    /** The problem with what is in the box, once somebody has been there. */
    error?: string | null
    children: ReactNode
    className?: string
}) {
    return (
        <div className={cn('flex min-w-0 flex-col gap-1.5', className)}>
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <Label htmlFor={id} className={cn('leading-5', mono && 'font-mono')}>
                    {label}
                </Label>
                {required && <span className="text-xs text-foreground">{LABELS.form.required}</span>}
                {hint !== undefined && <span className="text-xs text-faint">{hint}</span>}
                {fallback !== undefined && (
                    <span className="text-xs text-faint">{LABELS.form.default_is(fallback)}</span>
                )}
            </div>
            {children}
            {help !== undefined && (
                <p id={`${id}-help`} className="text-xs text-muted-foreground">
                    {help}
                </p>
            )}
            {error !== undefined && error !== null && (
                <p id={`${id}-error`} className="text-xs text-critical-ink">
                    {error}
                </p>
            )}
        </div>
    )
}

/** What a control in a `FormField` is described by, for its `aria-describedby`. */
export function describedBy(
    id: string,
    { help, error }: { help?: unknown; error?: string | null },
): string | undefined {
    const ids = [
        help !== undefined ? `${id}-help` : null,
        error !== undefined && error !== null ? `${id}-error` : null,
    ]
    const said = ids.filter((one) => one !== null).join(' ')
    return said === '' ? undefined : said
}
