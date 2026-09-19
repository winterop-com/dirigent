import { ChevronRight } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/lib/utils'

/**
 * A row that says where something stands, and opens under itself.
 *
 * THE ROW IS THE SUMMARY AND THE BODY IS UNDER IT, never in a pane of its own: a chevron saying
 * which way it is, what it is about, and the line it would read shut, with the body indented
 * against a rule while it is open. The step panel's engine groups and the thing a reference
 * field names are the same gesture, so they are one component.
 *
 * A ROW THAT OPENS NOTHING IS NOT A BUTTON. Given no `onToggle` it is a plain row with no
 * `aria-expanded` and no hover wash, because a control that cannot carry out what it offers is
 * chrome. Its chevron still says which way the row is.
 *
 * AN OPEN ROW SAYS NOTHING ITS BODY DOES NOT, so the summary is the shut state's alone and comes
 * back when the row shuts.
 */
export function Disclosure({
    title,
    summary,
    open,
    onToggle,
    children,
}: {
    /** What the row is about, on the left. */
    title: ReactNode
    /** The line the row reads while it is shut, or nothing. */
    summary?: ReactNode
    open: boolean
    /** How to turn the row over, or nothing where there is nothing to open. */
    onToggle: (() => void) | null
    children: ReactNode
}) {
    const row = (
        <>
            <ChevronRight className={cn('size-3 shrink-0 self-center', open && 'rotate-90')} aria-hidden />
            <span className="shrink-0 text-sm font-medium">{title}</span>
            {!open && summary}
        </>
    )
    return (
        <div>
            {onToggle === null ? (
                <div className="flex w-full items-baseline gap-2 py-1.5">{row}</div>
            ) : (
                <button
                    type="button"
                    aria-expanded={open}
                    onClick={onToggle}
                    className="row-hover flex w-full items-baseline gap-2 rounded-sm py-1.5 text-left"
                >
                    {row}
                </button>
            )}
            {open && <div className="my-1 ml-5 border-l border-primary py-1 pl-3">{children}</div>}
        </div>
    )
}
