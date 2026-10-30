import { createContext, useContext, type ReactNode } from 'react'

import { cn } from '@/lib/utils'

/** `grid` is a term column beside a value column; `row` is facts side by side on one wrapping line. */
export type FactLayout = 'grid' | 'row'

const Layout = createContext<FactLayout>('grid')

/**
 * A definition list of facts about one thing, in one of two layouts.
 *
 * `grid` is the panel's: terms in a column at body size, values beside them. `row` is the strip
 * under a heading: small facts that wrap as a line.
 */
export function FactList({
    variant = 'grid',
    children,
    className,
}: {
    variant?: FactLayout
    children: ReactNode
    className?: string
}) {
    return (
        <Layout.Provider value={variant}>
            <dl
                className={cn(
                    variant === 'grid'
                        ? 'grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-4 gap-y-1.5 text-sm'
                        : 'flex flex-wrap items-baseline gap-x-5 gap-y-1 text-xs',
                    className,
                )}
            >
                {children}
            </dl>
        </Layout.Provider>
    )
}

/**
 * One fact: a lower-case term and its value.
 *
 * `mono` is for a value that is a key, typed rather than read. `truncate` keeps a long value on
 * one line, its whole text on hover; otherwise it wraps.
 */
export function Fact({
    term,
    children,
    mono = false,
    truncate = false,
    title,
}: {
    term: string
    children: ReactNode
    mono?: boolean
    truncate?: boolean
    title?: string
}) {
    const layout = useContext(Layout)
    const value = cn('min-w-0', mono && 'font-mono', truncate ? 'truncate' : 'break-words')
    if (layout === 'row') {
        return (
            <div className="flex min-w-0 items-baseline gap-1.5">
                <dt className="shrink-0 text-faint">{term}</dt>
                <dd className={cn(value, 'text-foreground')} title={title}>
                    {children}
                </dd>
            </div>
        )
    }
    return (
        <>
            <dt className="text-muted-foreground">{term}</dt>
            <dd className={value} title={title}>
                {children}
            </dd>
        </>
    )
}
